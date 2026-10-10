"""Act names: normalisation, a curated table, per-court resolution, crosswalk.

The eCourts portals file every case under an act, but each court keeps its
own act list with its own codes and spellings. The same act is code ``1``,
"INDIAN PENAL CODE", on the Delhi High Court and code ``535``, "PENAL CODE,
1860", on Gujarat's. Lists are full of variants and debris besides:
"INDIAN PENAL CODE1", "I.P.C(POLICE)", "Domestic Violance Act 2005", and
look-alikes that must *not* match, such as "Code of Criminal Procedure
(Bombay Amendment) Act" or "Motor Vehicles Act, 1939".

This module turns a name a person would type ("IPC", "NI Act", "Negotiable
Instruments Act, 1881") into the matching codes on one court's list:

- :data:`ACTS` is a curated table of frequently litigated central acts.
- :func:`normalize_act_name` reduces a name to a comparable form: case,
  punctuation, a leading "the", the word "act", abbreviation brackets and
  plurals are dropped. Years are kept aside to tell versions apart.
- :func:`resolve` matches a query against a court's list. A query naming an
  act in :data:`ACTS` matches its known names exactly, then near-misses of
  its longer names; any other query falls back to matching the court's
  names directly. A year on either side must agree, so "Motor Vehicles Act,
  1939" never answers for the 1988 Act.
- :func:`successor_sections` maps a section of a code repealed on 1 July
  2024 to its successor: IPC → BNS, CrPC → BNSS, Evidence Act → BSA.

Resolution is deliberately conservative, so check the result: an empty
result means "this court's list has no recognisable entry for the act", not
"no cases".
"""

from __future__ import annotations

import csv
import difflib
import html
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field
from functools import cache
from importlib import resources
from pathlib import Path

from bharat_courts.models import _Serializable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

#: A plausible statute year. Anchored on digits only, so "ACT1940" still
#: yields 1940 while "(61 OF 1985)" is removed as a whole first.
_YEAR_RE = re.compile(r"(?<!\d)(1[789]\d\d|20\d\d)(?!\d)")

#: "(61 of 1985)" — an act number, not part of the name.
_ACT_NUMBER_RE = re.compile(r"\s*\d+\s+of\s+\d{4}\s*")

#: Words that carry no identity: "The Arms Act" and "Arms" are the same act.
_STOPWORDS = frozenset({"the", "act"})


@dataclass(frozen=True)
class _Normalized:
    text: str
    years: frozenset[int]


def _strip_bracket(match: re.Match[str]) -> str:
    """Drop an act number or an abbreviation in brackets, keep anything else.

    "(I.P.C)" and "(POCSO)" restate the name, and "(POLICE)" in
    "I.P.C(POLICE)" annotates it; all are short, letters-only, and dropped.
    Longer brackets carry identity — "(Bombay Amendment)", "(Regulation and
    Development)" — and are kept as plain words.
    """
    content = match.group(1)
    if _ACT_NUMBER_RE.fullmatch(content):
        return " "
    letters = content.replace(" ", "")
    if letters.isalpha() and len(letters) <= 6:
        return " "
    return f" {content} "


def _normalize(name: str) -> _Normalized:
    text = html.unescape(name).lower()
    # Before anything else: "I.P.C" → "ipc", "CR.P.C" → "crpc".
    text = text.replace(".", "")
    text = re.sub(r"\(([^()]*)\)", _strip_bracket, text)
    text = text.replace("&", " and ")
    years = frozenset(int(y) for y in _YEAR_RE.findall(text))
    text = re.sub(r"\d+", " ", text)
    text = re.sub(r"[^a-z]+", " ", text)
    tokens = []
    for token in text.split():
        if token in _STOPWORDS:
            continue
        # Crude plural folding — applied to both sides, so it only has to be
        # consistent: "Instruments"/"Instrument", "Offences"/"Offence".
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return _Normalized(" ".join(tokens), years)


def normalize_act_name(name: str) -> str:
    """Reduce an act name to the form used for matching.

    >>> normalize_act_name("The Negotiable Instruments Act, 1881")
    'negotiable instrument'
    >>> normalize_act_name("I.P.C(POLICE)")
    'ipc'
    """
    return _normalize(name).text


def _years_agree(a: frozenset[int], b: frozenset[int]) -> bool:
    """Whether two year sets can describe the same act.

    Either side may be silent; when both name years, they must share one
    ("Code of Criminal Procedure, 1973, 1974" is still the 1973 Code).
    """
    return not a or not b or bool(a & b)


# ---------------------------------------------------------------------------
# Curated act table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Act(_Serializable):
    """A central act, with the names it goes by.

    ``key`` is a stable slug used across the SDK — notably by the crosswalk,
    whose keys for the three replaced codes are ``ipc``/``bns``,
    ``crpc``/``bnss`` and ``iea``/``bsa``.
    """

    key: str
    name: str
    year: int | None = None
    aliases: tuple[str, ...] = ()
    #: Key of the act that replaced this one, e.g. ``"bns"`` for IPC.
    successor: str | None = None

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


#: Frequently litigated central acts. Aliases are the names and
#: abbreviations seen on court act lists and in everyday use.
#:
#: "Arbitration" is an alias of the 1996 Act on purpose. Unaliased, the query
#: "arbitration" matched only "Arbitration Act 1940" exactly (the year is set
#: aside when comparing names), hiding the Act people mean. As an alias, the
#: 1996 year excludes the 1940 entries while undated "ARBITRATION" entries
#: still match. Ask for "Arbitration Act 1940" to reach the old Act.
ACTS: dict[str, Act] = {
    a.key: a
    for a in (
        Act("ipc", "Indian Penal Code", 1860, ("IPC", "Penal Code"), successor="bns"),
        Act("bns", "Bharatiya Nyaya Sanhita", 2023, ("BNS",)),
        Act(
            "crpc",
            "Code of Criminal Procedure",
            1973,
            ("CrPC", "Criminal Procedure Code"),
            successor="bnss",
        ),
        Act("bnss", "Bharatiya Nagarik Suraksha Sanhita", 2023, ("BNSS",)),
        Act("iea", "Indian Evidence Act", 1872, ("IEA", "Evidence Act"), successor="bsa"),
        Act("bsa", "Bharatiya Sakshya Adhiniyam", 2023, ("BSA", "Bharatiya Sakshya Act")),
        Act("cpc", "Code of Civil Procedure", 1908, ("CPC", "Civil Procedure Code")),
        Act("ni", "Negotiable Instruments Act", 1881, ("NI Act",)),
        Act("ndps", "Narcotic Drugs and Psychotropic Substances Act", 1985, ("NDPS Act",)),
        Act("pocso", "Protection of Children from Sexual Offences Act", 2012, ("POCSO Act",)),
        Act("pc", "Prevention of Corruption Act", 1988, ("PC Act",)),
        Act("arms", "Arms Act", 1959),
        Act("arbitration", "Arbitration and Conciliation Act", 1996, ("Arbitration",)),
        Act("specific-relief", "Specific Relief Act", 1963),
        Act("limitation", "Limitation Act", 1963),
        Act("tpa", "Transfer of Property Act", 1882, ("TP Act",)),
        Act("contract", "Indian Contract Act", 1872, ("Contract Act",)),
        Act("companies-2013", "Companies Act", 2013),
        Act("companies-1956", "Companies Act", 1956),
        Act("ibc", "Insolvency and Bankruptcy Code", 2016, ("IBC",)),
        Act(
            "sarfaesi",
            "Securitisation and Reconstruction of Financial Assets and "
            "Enforcement of Security Interest Act",
            2002,
            ("SARFAESI Act",),
        ),
        Act("income-tax", "Income-tax Act", 1961),
        Act("cgst", "Central Goods and Services Tax Act", 2017, ("CGST Act",)),
        Act("customs", "Customs Act", 1962),
        Act("mv", "Motor Vehicles Act", 1988, ("MV Act",)),
        Act(
            "dv",
            "Protection of Women from Domestic Violence Act",
            2005,
            ("DV Act", "Domestic Violence Act"),
        ),
        Act("hma", "Hindu Marriage Act", 1955, ("HMA",)),
        Act("hsa", "Hindu Succession Act", 1956),
        Act("consumer-2019", "Consumer Protection Act", 2019),
        Act("consumer-1986", "Consumer Protection Act", 1986),
        Act("rera", "Real Estate (Regulation and Development) Act", 2016, ("RERA",)),
        Act("id", "Industrial Disputes Act", 1947, ("ID Act",)),
        Act("constitution", "Constitution of India", None, ("Constitution",)),
        Act("dowry", "Dowry Prohibition Act", 1961),
        Act(
            "sc-st",
            "Scheduled Castes and the Scheduled Tribes (Prevention of Atrocities) Act",
            1989,
            ("SC/ST Act", "SC ST (Prevention of Atrocities) Act"),
        ),
        Act(
            "jj",
            "Juvenile Justice (Care and Protection of Children) Act",
            2015,
            ("JJ Act",),
        ),
        Act("it", "Information Technology Act", 2000),
        Act("pmla", "Prevention of Money-laundering Act", 2002, ("PMLA",)),
        Act("uapa", "Unlawful Activities (Prevention) Act", 1967, ("UAPA",)),
        Act("land-acquisition", "Land Acquisition Act", 1894),
        Act(
            "rfctlarr",
            "Right to Fair Compensation and Transparency in Land Acquisition, "
            "Rehabilitation and Resettlement Act",
            2013,
        ),
        Act("succession", "Indian Succession Act", 1925),
        Act("guardians", "Guardians and Wards Act", 1890),
        Act("family-courts", "Family Courts Act", 1984),
        Act("commercial-courts", "Commercial Courts Act", 2015),
        Act("rti", "Right to Information Act", 2005, ("RTI Act",)),
        Act("electricity", "Electricity Act", 2003),
        Act("stamp", "Indian Stamp Act", 1899),
        Act("registration", "Registration Act", 1908),
        Act(
            "employees-compensation",
            "Employees' Compensation Act",
            1923,
            ("Workmen's Compensation Act",),
        ),
        Act("gratuity", "Payment of Gratuity Act", 1972),
    )
}


@cache
def _act_forms(key: str) -> tuple[str, ...]:
    """Normalised names of a curated act, longest first."""
    forms = {_normalize(n).text for n in ACTS[key].names}
    return tuple(sorted(forms - {""}, key=len, reverse=True))


def _act_years(act: Act) -> frozenset[int]:
    return frozenset() if act.year is None else frozenset({act.year})


def lookup_acts(query: str) -> list[Act]:
    """The curated acts a query names, if any.

    Usually one. Two when a name is shared and the query gives no year:
    "Companies Act" is both the 1956 and the 2013 Act, and the court lists
    may hold either. A year in the query picks between them.
    """
    q = _normalize(query)
    if not q.text:
        return []
    candidates = [a for a in ACTS.values() if _years_agree(q.years, _act_years(a))]
    exact = [a for a in candidates if q.text in _act_forms(a.key)]
    if exact:
        return exact
    # A misspelled query ("Domestic Violance") still names a curated act.
    return [
        a
        for a in candidates
        if max((_near_miss(q.text, f) for f in _act_forms(a.key)), default=0.0) >= FUZZY_THRESHOLD
    ]


# ---------------------------------------------------------------------------
# Resolution against a court's act list
# ---------------------------------------------------------------------------

#: Similarity needed for a near-miss. Measured on real court lists: genuine
#: misspellings score 0.94 and up ("Domestic Violance", "Bharatiya Nyay
#: Sanhita", "Arbitration and Concilation"), while the closest wrong pair,
#: "Code of Civil Procedure" vs "Code of Criminal Procedure", scores 0.898.
FUZZY_THRESHOLD = 0.92

#: Shorter names are too close to each other for near-miss matching to be
#: safe ("arm" vs "army"); only exact matches count for them.
_FUZZY_MIN_LEN = 12

#: Words that make a different instrument out of an act's name. "Narcotic
#: Drugs and Psychotropic Substances Rules" scores 0.94 against the Act, but
#: a case under the Rules is not a case under the Act — so a near-miss that
#: adds one of these is refused outright, whatever its score. (Stemmed, as
#: :func:`_normalize` leaves them.)
_QUALIFIERS = frozenset(
    {"rule", "amendment", "order", "regulation", "ordinance", "extension", "scheme", "validation"}
)


@dataclass(frozen=True)
class ActMatch(_Serializable):
    """One entry of a court's act list that a query resolved to."""

    code: str
    name: str
    #: How it matched: ``"alias"`` (a known name of a curated act),
    #: ``"exact"`` / ``"token"`` (direct match of a free-text query), or
    #: ``"fuzzy"`` (a near-miss, either way).
    tier: str
    score: float = 1.0
    #: Key of the curated act it matched, when the query named one.
    act_key: str | None = None


def _near_miss(candidate: str, target: str) -> float:
    """Similarity of ``candidate`` to ``target``, or 0 when it can't be one.

    Refused outright when either is too short to compare safely, or when
    the candidate adds a qualifier ("rule", "amendment", ...) the target
    lacks.
    """
    if len(candidate) < _FUZZY_MIN_LEN or len(target) < _FUZZY_MIN_LEN:
        return 0.0
    if (set(candidate.split()) - set(target.split())) & _QUALIFIERS:
        return 0.0
    return difflib.SequenceMatcher(None, candidate, target).ratio()


def _resolve_curated(acts: list[Act], entries: dict[str, _Normalized], names: dict[str, str]):
    out: dict[str, ActMatch] = {}
    for act in acts:
        forms = _act_forms(act.key)
        years = _act_years(act)
        for code, entry in entries.items():
            if code in out or not entry.text or not _years_agree(entry.years, years):
                continue
            if entry.text in forms:
                out[code] = ActMatch(code, names[code], "alias", 1.0, act.key)
                continue
            best = max((_near_miss(entry.text, f) for f in forms), default=0.0)
            if best >= FUZZY_THRESHOLD:
                out[code] = ActMatch(code, names[code], "fuzzy", round(best, 3), act.key)
    return list(out.values())


def _resolve_free_text(q: _Normalized, entries: dict[str, _Normalized], names: dict[str, str]):
    candidates = {c: e for c, e in entries.items() if e.text and _years_agree(q.years, e.years)}

    exact = [ActMatch(c, names[c], "exact") for c, e in candidates.items() if e.text == q.text]
    if exact:
        return exact

    q_tokens = set(q.text.split())
    token = [
        ActMatch(c, names[c], "token", round(len(q.text) / len(e.text), 3))
        for c, e in candidates.items()
        if q_tokens <= set(e.text.split())
    ]
    if token:
        return token

    fuzzy = []
    for c, e in candidates.items():
        score = _near_miss(e.text, q.text)
        if score >= FUZZY_THRESHOLD:
            fuzzy.append(ActMatch(c, names[c], "fuzzy", round(score, 3)))
    return fuzzy


def resolve(query: str | Act, act_list: dict[str, str]) -> list[ActMatch]:
    """Find the entries of one court's act list that a query refers to.

    Args:
        query: An act name as a person would type it ("IPC", "NI Act",
            "Negotiable Instruments Act, 1881"), or an :class:`Act`.
        act_list: The court's list, code → name, from ``list_acts()``.

    Returns:
        Every matching entry, best first. One act often has several codes on
        one court — Delhi lists five for arbitration — and all are returned,
        since cases are spread across them. Empty when nothing matches.

    A query naming a curated act (see :func:`lookup_acts`) matches that act's
    known names, then near-misses of its longer names. Anything else is
    matched directly against the court's names: an exact match if there is
    one, otherwise every entry containing all the query's words, otherwise
    near-misses. The direct route is broad by design — "arbitration" also
    finds "Goa, Daman and Diu (Extension of ... the Arbitration Act) Act" —
    so inspect the result for free-text queries.
    """
    entries = {code: _normalize(name) for code, name in act_list.items()}
    acts = [query] if isinstance(query, Act) else lookup_acts(query)
    if acts:
        matches = _resolve_curated(acts, entries, act_list)
    else:
        matches = _resolve_free_text(_normalize(query), entries, act_list)
    return sorted(matches, key=lambda m: (-m.score, m.name))


# ---------------------------------------------------------------------------
# Per-court act list cache
# ---------------------------------------------------------------------------

_DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "bharat-courts" / "acts"
_DEFAULT_TTL_SECONDS = 7 * 86400


class _ActListCache:
    """On-disk cache of court act lists, one JSON file per court.

    The lists are free to fetch but there are many courts, and they change
    rarely — so a week's TTL by default, overridable with
    ``BHARAT_COURTS_ACTS_TTL_DAYS``. Keys are per bench and per
    establishment: Bombay's principal bench and its Aurangabad bench keep
    different lists (4,545 vs 4,541 entries, measured live).
    """

    def __init__(
        self,
        *,
        cache_dir: Path | str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        env_ttl = os.environ.get("BHARAT_COURTS_ACTS_TTL_DAYS")
        if ttl_seconds is None and env_ttl:
            try:
                ttl_seconds = int(float(env_ttl) * 86400)
            except ValueError:
                ttl_seconds = None
        self.cache_dir = Path(cache_dir or _DEFAULT_CACHE_ROOT)
        # NOTE: ``ttl_seconds or DEFAULT`` would silently override the legal
        # value 0 ("always stale") with the default, so be explicit.
        self.ttl_seconds = _DEFAULT_TTL_SECONDS if ttl_seconds is None else ttl_seconds

    @staticmethod
    def hc_key(state_code: str, bench_code: str) -> str:
        return f"hc_{state_code}_{bench_code}"

    @staticmethod
    def dc_key(state_code: str, dist_code: str, court_complex_code: str, est_code: str) -> str:
        return f"dc_{state_code}_{dist_code}_{court_complex_code}_{est_code or '0'}"

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[\w-]+", key):
            raise ValueError(f"invalid cache key {key!r}")
        return self.cache_dir / f"{key}.json"

    def load(self, key: str) -> dict[str, str] | None:
        """The cached list, or ``None`` when missing, stale or unreadable."""
        path = self._path(key)
        try:
            age = time.time() - path.stat().st_mtime
            # Clamp: mtime can sit marginally in the future right after a
            # write, and a TTL of 0 must reliably mean "always stale".
            if max(0.0, age) >= self.ttl_seconds:
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def save(self, key: str, acts: dict[str, str]) -> None:
        """Store a list atomically. An empty list is not cached — it is more
        likely a portal hiccup than a court with no acts."""
        if not acts:
            return
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".w_", suffix=".part", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(acts, f, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# Crosswalk: repealed codes → successors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionMapping(_Serializable):
    """One section of a repealed code and where it went.

    ``new_section`` is as the source table prints it ("103(1)", "Proviso to
    section 23"); ``new_section_base`` is the bare section number, which is
    what a portal's section box accepts.
    """

    old_act: str
    old_section: str
    new_act: str
    new_section: str
    new_section_base: str
    source_page: int = 0
    source: str = field(default="", repr=False)


@cache
def _crosswalk() -> dict[tuple[str, str], tuple[SectionMapping, ...]]:
    text = (resources.files("bharat_courts") / "data" / "crosswalk.csv").read_text(encoding="utf-8")
    rows = csv.DictReader(line for line in text.splitlines() if not line.startswith("#"))
    index: dict[tuple[str, str], list[SectionMapping]] = {}
    for row in rows:
        mapping = SectionMapping(
            old_act=row["old_act"],
            old_section=row["old_section"],
            new_act=row["new_act"],
            new_section=row["new_section"],
            new_section_base=row["new_section_base"],
            source_page=int(row["source_page"] or 0),
            source=row["source"],
        )
        index.setdefault((mapping.old_act, mapping.old_section), []).append(mapping)
    return {k: tuple(v) for k, v in index.items()}


def _section_key(section: str) -> str:
    """``"498a"`` → ``"498A"``; ``"376(2)"`` → ``"376"``."""
    return re.sub(r"\(.*", "", section).replace(" ", "").upper()


def successor_sections(act: str | Act, section: str) -> list[SectionMapping]:
    """Where a section of IPC, CrPC or the Evidence Act went on 1 July 2024.

    Cases registered from that date cite the new codes, so a search for
    "IPC 302" alone misses recent murder cases filed as "BNS 103".

    Args:
        act: ``"ipc"``, ``"crpc"`` or ``"iea"`` (or their names, or the
            :class:`Act`). Other acts have no successor and return ``[]``.
        section: The old section, e.g. ``"302"`` or ``"498A"``.

    Returns:
        The successor sections — sometimes several: IPC 376 became BNS 64
        and 65(1), IPC 498A became BNS 85 and 86. Empty when the section
        was dropped or the act has no successor.

    Source: correspondence tables by the Central Academy for Police
    Training, Bhopal; each mapping carries its source page.
    """
    if isinstance(act, Act):
        key = act.key
    else:
        found = lookup_acts(act)
        key = found[0].key if found else act.strip().lower()
    return list(_crosswalk().get((key, _section_key(section)), ()))


__all__ = [
    "ACTS",
    "Act",
    "ActMatch",
    "FUZZY_THRESHOLD",
    "SectionMapping",
    "lookup_acts",
    "normalize_act_name",
    "resolve",
    "successor_sections",
]
