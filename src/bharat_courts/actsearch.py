"""Search by act across High Courts — one call, every court, every code.

:meth:`HCServicesClient.case_status_by_act` searches one act code on one
bench. Answering "which pending cases are filed under the NI Act, s.138, in
Delhi and Bombay?" takes much more than that: each court's act list has to
be fetched and the act name resolved against it (codes and spellings are
local to each court, and one act is often filed under several codes), then
every code searched, the results merged and de-duplicated. :class:`ActSearch`
does all of it::

    async with ActSearch() as s:
        res = await s.cases(act="NI Act", section="138", courts=["delhi", "bombay"])
        res.hits         # one ActCaseHit per case, tagged with the act code it matched
        res.resolution   # per court: which codes "NI Act" resolved to ([] = not listed)
        res.errors       # per court: what failed — the other courts' hits are kept

        # Judgments whose text *mentions* the act (judgments portal):
        hits = await s.judgments(act="NI Act", section="138", text="cheque dishonour")

Two meanings, kept apart on purpose:

- :meth:`ActSearch.cases` finds cases the court **registered under** the act —
  its own record of what a case was filed under.
- :meth:`ActSearch.judgments` finds judgments that **mention** the act —
  a text match on the judgments portal.

Each case search costs a CAPTCHA solve per court × act code × section ×
status; the plan is logged at INFO before anything is sent.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Self

from bharat_courts.acts import (
    ACTS,
    Act,
    ActMatch,
    _ActListCache,
    lookup_acts,
    resolve,
    successor_sections,
)
from bharat_courts.captcha import default_solver
from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config
from bharat_courts.courts import get_court, infer_court_from_cnr, list_high_courts
from bharat_courts.facade import live_to_judgment
from bharat_courts.hcservices.endpoints import validate_section
from bharat_courts.models import CaseInfo, Court, CourtType, Judgment, _Serializable

logger = logging.getLogger(__name__)

#: ``courts=`` shorthand for every High Court's principal bench.
ALL_HIGH_COURTS = "all-hc"


@dataclass
class ActCaseHit(_Serializable):
    """A case found by an act search, with what it matched."""

    case: CaseInfo
    court: Court
    #: The court's code for the act, and its name on the court's list.
    act_code: str
    act_name: str
    #: The section searched ("" for all sections).
    section: str = ""
    bench_code: str = "1"
    #: Key of the curated act matched (e.g. "bns" when found through the
    #: IPC → BNS crosswalk), if the act is in :data:`bharat_courts.acts.ACTS`.
    act_key: str | None = None
    #: The archived judgment, when ``with_judgments=True`` found one.
    judgment: Judgment | None = None


@dataclass
class ActSearchResult(_Serializable):
    """Everything an act search found, resolved and failed, per court."""

    act: str
    sections: list[str] = field(default_factory=list)
    status: str = "Pending"
    hits: list[ActCaseHit] = field(default_factory=list)
    #: Court code → the act-list entries the query resolved to. An empty
    #: list means the act isn't on that court's list (e.g. no BNS entry),
    #: which is why the court has no hits — not that it has no such cases.
    resolution: dict[str, list[ActMatch]] = field(default_factory=dict)
    #: Court code → what went wrong there. Other courts' hits are kept.
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def cases(self) -> list[CaseInfo]:
        return [h.case for h in self.hits]


@dataclass(frozen=True)
class _Target:
    """One act-code search: a court bench, a resolved code, a section."""

    court: Court
    bench_code: str
    match: ActMatch
    section: str


def _as_list(section: str | Sequence[str] | None) -> list[str]:
    if section is None:
        return [""]
    if isinstance(section, str):
        return [section]
    return list(section) or [""]


def _resolve_courts(courts: Court | str | Sequence[Court | str]) -> list[Court]:
    if isinstance(courts, (Court, str)):
        courts = [courts]
    out: list[Court] = []
    for c in courts:
        if c == ALL_HIGH_COURTS:
            # Principal entries only: the registry's bench entries
            # ("bombay-nagpur") share their state code with the principal
            # and carry no portal bench code. Use all_benches=True instead.
            out.extend(h for h in list_high_courts() if h.bench is None)
            continue
        court = c if isinstance(c, Court) else get_court(c)
        if court is None:
            raise ValueError(f"unknown court {c!r}")
        if court.court_type != CourtType.HIGH_COURT:
            raise ValueError(f"{court.name} is not a High Court; act search covers High Courts")
        out.append(court)
    # Drop repeats, keep first-seen order (same code → same court).
    return list({c.code: c for c in out}.values())


class ActSearch:
    """Act search across High Courts, plus act-filtered judgment search.

    Args:
        config: SDK config, shared by every client this creates.
        captcha_solver: Shared by all workers. Defaults to the best
            available solver, as the clients do.
        cache_dir: Where court act lists are cached (default
            ``~/.cache/bharat-courts/acts``).
        use_cache: Set False to always fetch act lists fresh.
    """

    def __init__(
        self,
        *,
        config: BharatCourtsConfig | None = None,
        captcha_solver: CaptchaSolver | None = None,
        cache_dir: str | None = None,
        use_cache: bool = True,
    ) -> None:
        self._config = config or default_config
        self._solver = captcha_solver
        self._cache = _ActListCache(cache_dir=cache_dir) if use_cache else None
        self._archive: Any = None
        self._live: Any = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._archive is not None:
            await self._archive.close()
            self._archive = None
        if self._live is not None:
            # JudgmentSearchClient has __aexit__ but no aclose().
            await self._live.__aexit__(None, None, None)
            self._live = None

    def _captcha_solver(self) -> CaptchaSolver:
        if self._solver is None:
            self._solver = default_solver()
        return self._solver

    def _hc_client(self):
        from bharat_courts.hcservices.client import HCServicesClient

        return HCServicesClient(config=self._config, captcha_solver=self._captcha_solver())

    # ------------------------------------------------------------------
    # Act lists
    # ------------------------------------------------------------------

    async def court_acts(self, court: Court | str, *, bench_code: str = "1") -> dict[str, str]:
        """A High Court bench's act list, from the cache when fresh."""
        court = _resolve_courts(court)[0]
        key = _ActListCache.hc_key(court.state_code, bench_code)
        if self._cache is not None:
            cached = self._cache.load(key)
            if cached is not None:
                return cached
        async with self._hc_client() as client:
            acts = await client.list_acts(court, bench_code=bench_code)
        if self._cache is not None:
            self._cache.save(key, acts)
        return acts

    async def resolve(
        self, act: str | Act, court: Court | str, *, bench_code: str = "1"
    ) -> list[ActMatch]:
        """Which entries of a court's act list ``act`` refers to."""
        return resolve(act, await self.court_acts(court, bench_code=bench_code))

    # ------------------------------------------------------------------
    # Case search
    # ------------------------------------------------------------------

    async def cases(
        self,
        *,
        act: str | Act,
        courts: Court | str | Sequence[Court | str],
        section: str | Sequence[str] | None = None,
        status: str = "Pending",
        year: int | tuple[int, int] | None = None,
        include_successor: bool = False,
        all_benches: bool = False,
        bench_code: str = "1",
        concurrency: int = 2,
        with_judgments: bool = False,
    ) -> ActSearchResult:
        """Find cases registered under an act on one or more High Courts.

        Args:
            act: Act name as a person would type it ("NI Act", "IPC",
                "Negotiable Instruments Act, 1881"), or an :class:`Act`.
            courts: Court codes or objects, or ``"all-hc"`` for every High
                Court's principal bench.
            section: One section, or several ("138", ["302", "34"]) —
                searched separately, since the portal matches exactly.
                None searches all sections.
            status: "Pending", "Disposed" or "Both" ("Both" doubles the
                CAPTCHA solves).
            year: Registration year or inclusive range, filtered after
                download (the portal has no year filter).
            include_successor: Also search the successor code — for IPC
                302 also BNS 103, via
                :func:`~bharat_courts.acts.successor_sections`. Cases
                registered from 1 July 2024 cite the new codes.
            all_benches: Search every bench of each court (from
                ``list_benches``) instead of ``bench_code`` alone.
            bench_code: Bench to search when ``all_benches`` is False.
            concurrency: Searches in flight at once. Each runs its own
                session, so this multiplies the request rate on the portal.
            with_judgments: For disposed hits, attach the archived judgment
                (needs the ``[archive]`` extra). Joined on CNR, one archive
                query per court and decision year; hits carrying another
                court's CNR are skipped. The archive lags the portal and its
                coverage varies by court and year, so expect gaps.

        Returns:
            An :class:`ActSearchResult`. One court failing does not discard
            the others: its error is in ``errors`` and its hits are absent.

        Raises:
            ValueError: On an unknown court, an invalid section or status,
                or before any request is sent.
        """
        sections = _as_list(section)
        for s in sections:
            validate_section(s)
        if status not in ("Pending", "Disposed", "Both"):
            raise ValueError(f"status must be 'Pending', 'Disposed' or 'Both', got {status!r}")
        court_list = _resolve_courts(courts)
        queries = self._queries(act, sections, include_successor)
        result = ActSearchResult(
            act=act.name if isinstance(act, Act) else act, sections=sections, status=status
        )

        targets = await self._plan(court_list, queries, all_benches, bench_code, result)
        solves = len(targets) * (2 if status == "Both" else 1)
        logger.info(
            "Act search: %d searches over %d court(s), ~%d CAPTCHA solves",
            len(targets),
            len(court_list),
            solves,
        )

        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def run(target: _Target) -> list[ActCaseHit]:
            async with semaphore, self._hc_client() as client:
                rows = await client.case_status_by_act(
                    target.court,
                    act_code=target.match.code,
                    section=target.section,
                    status_filter=status,
                    bench_code=target.bench_code,
                    year=year,
                )
            return [
                ActCaseHit(
                    case=row,
                    court=target.court,
                    act_code=target.match.code,
                    act_name=target.match.name,
                    section=target.section,
                    bench_code=target.bench_code,
                    act_key=target.match.act_key,
                )
                for row in rows
            ]

        outcomes = await asyncio.gather(*(run(t) for t in targets), return_exceptions=True)
        seen: set[tuple[str, str]] = set()
        for target, outcome in zip(targets, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                if not isinstance(outcome, Exception):
                    raise outcome
                self._record_error(
                    result,
                    target.court,
                    f"act {target.match.code}"
                    + (f" s.{target.section}" if target.section else "")
                    + f": {type(outcome).__name__}: {outcome}",
                )
                continue
            for hit in outcome:
                # One case can be filed under several of a court's codes for
                # the same act, or under both a section and its successor.
                key = (hit.court.code, hit.case.cnr_number or hit.case.case_number)
                if key not in seen:
                    seen.add(key)
                    result.hits.append(hit)

        if with_judgments:
            await self._attach_judgments(result)
        return result

    @staticmethod
    def _queries(
        act: str | Act, sections: list[str], include_successor: bool
    ) -> list[tuple[str | Act, str]]:
        """The (act, section) pairs to search, successors included."""
        queries: list[tuple[str | Act, str]] = [(act, s) for s in sections]
        if not include_successor:
            return queries
        curated = [act] if isinstance(act, Act) else lookup_acts(act)
        for old in curated:
            if not old.successor:
                continue
            new = ACTS[old.successor]
            for s in sections:
                if not s:
                    queries.append((new, ""))
                    continue
                bases = {m.new_section_base for m in successor_sections(old, s)}
                if not bases:
                    logger.info("%s s.%s has no successor section", old.name, s)
                queries.extend((new, b) for b in sorted(bases))
        # Drop repeats, keep order.
        return list(dict.fromkeys(queries))

    async def _plan(
        self,
        courts: list[Court],
        queries: list[tuple[str | Act, str]],
        all_benches: bool,
        bench_code: str,
        result: ActSearchResult,
    ) -> list[_Target]:
        """Resolve the act on every court's list; list the searches to run."""
        targets: list[_Target] = []
        for court in courts:
            try:
                benches = [bench_code]
                if all_benches:
                    async with self._hc_client() as client:
                        benches = list(await client.list_benches(court)) or [bench_code]
                matched: dict[str, ActMatch] = {}
                for bench in benches:
                    act_list = await self.court_acts(court, bench_code=bench)
                    for query, section in queries:
                        for m in resolve(query, act_list):
                            matched.setdefault(m.code, m)
                            targets.append(_Target(court, bench, m, section))
                result.resolution[court.code] = list(matched.values())
                if not matched:
                    logger.info("%s: %r is not on this court's act list", court.name, result.act)
            except Exception as e:  # one court's list failing must not sink the rest
                self._record_error(result, court, f"act list: {type(e).__name__}: {e}")
        return list(dict.fromkeys(targets))

    @staticmethod
    def _record_error(result: ActSearchResult, court: Court, message: str) -> None:
        logger.warning("%s: %s", court.name, message)
        previous = result.errors.get(court.code)
        result.errors[court.code] = f"{previous}; {message}" if previous else message

    async def _attach_judgments(self, result: ActSearchResult) -> None:
        """Join disposed hits to the archive on CNR, a query per court-year.

        Batched rather than one lookup per hit: a disposed list runs to
        thousands of cases, and the archive partitions by court and year, so
        each partition is read once whatever the number of hits in it.
        """

        def archived_here(hit: ActCaseHit) -> bool:
            # Rows can carry a trial court's CNR (DLND… on a Delhi HC
            # petition); the archive has no High Court judgment under it.
            issuer = infer_court_from_cnr(hit.case.cnr_number)
            return issuer is not None and issuer.state_code == hit.court.state_code

        groups: dict[tuple[str, int], list[ActCaseHit]] = {}
        for hit in result.hits:
            if hit.case.status == "Disposed" and hit.case.decision_date and archived_here(hit):
                groups.setdefault((hit.court.code, hit.case.decision_date.year), []).append(hit)
        if not groups:
            return
        try:
            archive = await self._get_archive()
        except ImportError as e:
            logger.warning("with_judgments skipped: %s", e)
            return

        for (_, year), hits in groups.items():
            cnrs = sorted({h.case.cnr_number for h in hits})
            try:
                found = await archive.search(
                    cnr=cnrs,
                    court=hits[0].court,
                    year=year,
                    # A case can have several archived orders in a year.
                    limit=len(cnrs) * 10,
                )
            except Exception as e:
                logger.warning("archive lookup failed for %s %d: %s", hits[0].court.name, year, e)
                continue
            # Newest first from the archive; keep each CNR's first (latest).
            by_cnr: dict[str, Judgment] = {}
            for judgment in found:
                if judgment.cnr:
                    by_cnr.setdefault(judgment.cnr, judgment)
            for hit in hits:
                hit.judgment = by_cnr.get(hit.case.cnr_number)
            logger.info(
                "with_judgments: %s %d — %d of %d in the archive",
                hits[0].court.name,
                year,
                len({h.case.cnr_number for h in hits} & by_cnr.keys()),
                len(cnrs),
            )

    async def _get_archive(self):
        if self._archive is None:
            try:
                from bharat_courts.archive.client import ArchiveClient
            except ImportError as e:
                raise ImportError(
                    "with_judgments needs the [archive] extra: pip install 'bharat-courts[archive]'"
                ) from e
            self._archive = ArchiveClient()
        return self._archive

    # ------------------------------------------------------------------
    # Judgment search
    # ------------------------------------------------------------------

    async def judgments(
        self,
        *,
        act: str,
        section: str = "",
        text: str = "",
        court_type: str = "2",
        limit: int = 50,
    ) -> list[Judgment]:
        """Judgments whose text **mentions** an act, from the judgments portal.

        A text match — broader than :meth:`cases`, which finds cases
        registered under the act. ``act`` is sent as typed after dropping
        digits and punctuation, so prefer the full name ("Negotiable
        Instruments Act") over an abbreviation the judgment text may not use.

        Args:
            act: Act name, full or partial.
            section: Section to pair with it.
            text: Optional keywords to narrow further.
            court_type: "2" for High Courts, "3" for SCR.
            limit: Maximum judgments (one page; the portal caps page size).
        """
        live = await self._get_live()
        sr = await live.search(
            text, act=act, section=section, court_type=court_type, page_size=min(limit, 100)
        )
        return [live_to_judgment(jr) for jr in sr.items[:limit]]

    async def _get_live(self):
        if self._live is None:
            from bharat_courts.judgments.client import JudgmentSearchClient

            self._live = JudgmentSearchClient(
                config=self._config, captcha_solver=self._captcha_solver()
            )
            await self._live.__aenter__()
        return self._live


__all__ = ["ALL_HIGH_COURTS", "ActCaseHit", "ActSearch", "ActSearchResult"]
