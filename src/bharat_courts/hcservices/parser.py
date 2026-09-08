"""Parsers for HC Services responses.

The portal returns two distinct response formats:
- **JSON** for case status search (action_code=showRecords) — the JS client
  receives JSON and renders it into DOM.  Structure:
  ``{"con": ["[{...}, ...]"], "totRecords": N, "Error": ""}``
- **HTML tables** for cause list (action_code=showCauseList) and some older
  endpoints.

Both formats are handled here.
"""

from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from bharat_courts.models import (
    AdvocateSearch,
    CaseInfo,
    CaseOrder,
    CauseListEntry,
    CauseListPDF,
)

logger = logging.getLogger(__name__)

DATE_FORMAT = "%d-%m-%Y"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_date(text: str) -> date | None:
    """Parse a portal date string.

    Most endpoints use DD-MM-YYYY, but the advocate cause list returns
    ``date_next_list`` as ISO (YYYY-MM-DD), so ISO is tried as a fallback.
    """
    text = text.strip()
    if not text or text.lower() in {"none", "null", "-", "--"}:
        return None
    for fmt in (DATE_FORMAT, "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    logger.debug("Could not parse date: %s", text)
    return None


def _clean_text(text: str | None) -> str:
    """Strip and normalize whitespace."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


# ---------------------------------------------------------------------------
# JSON response helpers
# ---------------------------------------------------------------------------


class CaptchaError(Exception):
    """Raised when the server rejects the CAPTCHA."""


class ServerError(Exception):
    """Raised on a non-empty Error field from the server."""


def _parse_json_envelope(raw: str) -> tuple[list[dict], int, dict]:
    """Parse the outer JSON envelope from showRecords responses.

    The envelope itself is returned alongside the rows because some searches
    keep more than the rows — an advocate search reads ``adv_name`` off it —
    and a second :func:`json.loads` would both double the parse cost on a
    multi-MB response and skip the leniency below.

    Returns:
        (records_list, total_count, envelope). The envelope is ``{}`` when
        the response was not JSON at all.

    Raises:
        CaptchaError: If the captcha was wrong.
        ServerError: If the server returned a non-empty Error field.
    """
    text = raw.strip().lstrip("\ufeff")

    # Quick check for plain-text error responses
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Some responses have control chars; try a lenient parse
            data = json.loads(text, strict=False)

        # Handle {"con": "Invalid Captcha"} or {"Error": "ERROR_VAL"}
        if isinstance(data.get("con"), str) and "captcha" in data["con"].lower():
            raise CaptchaError(data["con"])
        err = data.get("Error", "")
        if err and err != "":
            raise ServerError(err)

        con = data.get("con")
        total = int(data.get("totRecords") or 0)

        if isinstance(con, list) and con:
            # con is a list of JSON-encoded strings
            inner = con[0]
            if isinstance(inner, str):
                try:
                    records = json.loads(inner, strict=False)
                except json.JSONDecodeError:
                    logger.warning("Could not parse inner con JSON")
                    return [], total, data
            elif isinstance(inner, dict):
                records = [inner]
            else:
                records = []
            return records if isinstance(records, list) else [], total, data
        return [], total, data

    # Not JSON at all
    return [], 0, {}


#: ``{"con": "Invalid Captcha"}`` — but the wording drifts, so match any
#: ``con`` *string* mentioning a captcha, which is exactly what
#: :func:`_parse_json_envelope` raises :class:`CaptchaError` on. A successful
#: response carries ``"con": [...]``, a list, so it can never match.
_CAPTCHA_REJECTION_RE = re.compile(r'"con"\s*:\s*"[^"]*captcha', re.IGNORECASE)


def is_captcha_rejection(raw: str) -> bool:
    """Whether a showRecords response is the server refusing the CAPTCHA.

    The retry loop needs this verdict without paying for a full parse — a
    live advocate search answers with several MB — and it has to agree with
    :func:`_parse_json_envelope`. A quick-check that knows only the literal
    "Invalid Captcha" lets a reworded rejection through as a success; the
    parse then raises :class:`CaptchaError` on the first attempt with every
    remaining retry unused, and this portal's error wording has drifted
    before.
    """
    return bool(_CAPTCHA_REJECTION_RE.search(raw))


# ---------------------------------------------------------------------------
# Case status — JSON-based
# ---------------------------------------------------------------------------


def parse_case_status(raw: str) -> list[CaseInfo]:
    """Parse case status search results (JSON response from showRecords).

    The response envelope is ``{"con": ["[{...}]"], "totRecords": N}``.
    Each record in the inner array has these fields (verified live):
    ``orderurlpath, case_no, pet_name, case_no2, case_year, res_name,
    lpet_name, lres_name, cino, party_name1, party_name2, type_name``.

    Note: ``status``, ``status_name``, and ``reg_date`` are **not** returned
    by the showRecords endpoint. Status / registration date come from
    ``o_civil_case_history.php`` and are not populated here.
    """
    # Fall back to HTML parsing if the response is an HTML table
    if "<table" in raw.lower():
        return _parse_case_status_html(raw)

    records, total, _ = _parse_json_envelope(raw)
    return _case_infos_from_records(records, total)


def _case_infos_from_records(records: list[dict], total: int) -> list[CaseInfo]:
    """Map already-parsed showRecords rows to :class:`CaseInfo`.

    Split out of :func:`parse_case_status` so a caller that has already
    parsed the envelope (see :func:`parse_advocate_search`) can reuse the
    mapping without decoding the response a second time.
    """
    results = []
    for rec in records:
        case_no2 = str(rec.get("case_no2", ""))
        case_year = str(rec.get("case_year", ""))
        case_number_display = f"{case_no2}/{case_year}" if case_no2 and case_year else ""

        results.append(
            CaseInfo(
                case_number=case_number_display,
                case_type=rec.get("type_name") or "",
                cnr_number=rec.get("cino") or "",
                filing_number=rec.get("case_no") or "",
                registration_number=case_no2,
                petitioner=html.unescape(rec.get("pet_name") or ""),
                respondent=html.unescape(rec.get("res_name") or ""),
            )
        )

    logger.info("Parsed %d/%d case status records", len(results), total)
    return results


#: "MR. HEMAL SHAH(6960)" — name, then the portal's internal advocate id.
_ADV_ECHO_RE = re.compile(r"^(.*?)\s*\((\d+)\)\s*$")


def parse_advocate_search(raw: str) -> AdvocateSearch:
    """Parse an advocate search, keeping the advocate the portal matched.

    :func:`parse_case_status` discards the envelope, which is where the only
    confirmation of a bar code lives. Nothing else validates one — the
    portal's form takes the state part as free text on both High Court and
    district — so a mistyped code is not an error, just a search that finds
    nothing. The echo is what separates "this advocate has no pending
    matters" from "this bar code does not exist", and those need different
    words in front of a lawyer who has just signed up.

    Goes through :func:`_parse_json_envelope` like its siblings, so it
    inherits their handling of session-expired HTML, control characters in
    names, and a BOM behind leading whitespace — and parses the response
    once, which matters when a live bar code answers with thousands of rows.
    """
    # An HTML table means the portal answered with a page rather than the
    # JSON envelope, so there is no echo to keep — only the rows.
    if "<table" in raw.lower():
        return AdvocateSearch(cases=_parse_case_status_html(raw))

    records, total, envelope = _parse_json_envelope(raw)
    echoed = _clean_text(envelope.get("adv_name") or "")
    name, code = echoed, ""
    m = _ADV_ECHO_RE.match(echoed)
    if m:
        name, code = m.group(1).strip(), m.group(2)
    return AdvocateSearch(
        raw_name=echoed,
        name=name,
        code=code,
        total_records=total,
        cases=_case_infos_from_records(records, total),
    )


# ---------------------------------------------------------------------------
# Advocate cause list — JSON-based
# ---------------------------------------------------------------------------


def parse_advocate_cause_list(raw: str) -> list[CauseListEntry]:
    """Parse an advocate's cause list (``search_type=3`` from showRecords).

    Shares the ``{"con": ["[{...}]"]}`` envelope with case status, but the
    records carry listing fields that plain case status does not:
    ``date_next_list, purpose_name, court_no, judgename``.

    Two portal quirks worth knowing:

    - **Rows are a cross-product of parties and judges, not one per case.**
      Verified on GJHC240569342026, which returned **8 rows — 4 petitioners
      by the 2 judges of a division bench**. A count of rows is not a count
      of matters, and :func:`dedupe_by_cnr` collapses both dimensions, so the
      judge it keeps is one of the bench rather than the coram.
    - **Both dates are returned per row.** ``date_next_list`` is the listing
      being queried and ``todays_date`` is when the matter was last in court
      — so on a board fetched for 20-08-2026, ``todays_date`` read 18-08-2026.
      They are not two names for the same day.
    - **``court_no`` is an internal establishment code** (e.g. "5377"), not
      the court number shown on a display board. Join to a board on
      ``judge`` instead.

    No item/serial number is returned — that lives only in the cause list
    PDF, so :attr:`CauseListEntry.item_number` is left empty here.
    """
    records, total, _ = _parse_json_envelope(raw)
    results = []
    for rec in records:
        case_no2 = str(rec.get("case_no2", ""))
        case_year = str(rec.get("case_year", ""))
        results.append(
            CauseListEntry(
                serial_number=0,
                case_number=f"{case_no2}/{case_year}" if case_no2 and case_year else "",
                case_type=rec.get("type_name") or "",
                petitioner=html.unescape(rec.get("pet_name") or ""),
                respondent=html.unescape(rec.get("res_name") or ""),
                advocate_petitioner=html.unescape(rec.get("adv_name1") or ""),
                advocate_respondent=html.unescape(rec.get("adv_name2") or ""),
                court_number=str(rec.get("court_no") or ""),
                judge=html.unescape(rec.get("judgename") or ""),
                listing_date=_parse_date(str(rec.get("date_next_list") or "")),
                business_date=_parse_date(str(rec.get("todays_date") or "")),
                cnr_number=rec.get("cino") or "",
                purpose=html.unescape(rec.get("purpose_name") or ""),
            )
        )

    logger.info("Parsed %d/%d advocate cause list rows", len(results), total)
    return results


def dedupe_by_cnr(entries: list[CauseListEntry]) -> list[CauseListEntry]:
    """Collapse duplicate rows into one entry per case, preserving order.

    The portal repeats a case once per party *per judge*, so a 14-row
    response can be 4 actual matters. The first row for each CNR is kept.

    Note what that discards: on a division bench the surviving row names one
    judge, not the coram, and it names one party of several. Callers that
    need either should group the raw rows themselves rather than use this.
    """
    seen: set[str] = set()
    out = []
    for e in entries:
        key = e.cnr_number or f"{e.case_type}/{e.case_number}"
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


# ---------------------------------------------------------------------------
# Case status — HTML fallback (legacy)
# ---------------------------------------------------------------------------


def _extract_parties(cell: Tag) -> tuple[str, str]:
    """Extract petitioner and respondent from a 'Petitioner vs Respondent' cell."""
    strongs = cell.find_all("strong")
    if len(strongs) >= 2:
        return _clean_text(strongs[0].get_text()), _clean_text(strongs[1].get_text())

    text = _clean_text(cell.get_text())
    parts = re.split(r"\bvs?\b", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()

    return text, ""


def _parse_case_status_html(html: str) -> list[CaseInfo]:
    """Parse case status results from an HTML table (legacy format).

    Expected columns: Sr No | Case Number | Parties | Advocate |
    Filing Date | Reg Date | Status
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    results = []
    rows = table.find_all("tr")[1:]  # Skip header

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue

        case_number = _clean_text(cols[1].get_text())
        petitioner, respondent = _extract_parties(cols[2])
        filing_date = _parse_date(cols[4].get_text()) if len(cols) > 4 else None
        reg_date = _parse_date(cols[5].get_text()) if len(cols) > 5 else None
        status = _clean_text(cols[6].get_text()) if len(cols) > 6 else ""

        results.append(
            CaseInfo(
                case_number=case_number,
                case_type=case_number.split("/")[0] if "/" in case_number else "",
                filing_number=filing_date.isoformat() if filing_date else "",
                registration_date=reg_date,
                petitioner=petitioner,
                respondent=respondent,
                status=status,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Court orders
# ---------------------------------------------------------------------------


def parse_orders(
    raw: str,
    base_url: str = "",
    bench_code: str = "",
    state_code: str = "",
) -> list[CaseOrder]:
    """Parse orders from a showRecords JSON response or HTML table.

    The JSON response contains ``orderurlpath`` per case which is an encrypted
    path used to construct ``display_pdf.php`` URLs.  Falls back to HTML table
    parsing for legacy responses.
    """
    # Try JSON first (preferred — from case_status search)
    stripped = raw.strip().lstrip("\ufeff")
    if not stripped.startswith("<"):
        try:
            records, _, _ = _parse_json_envelope(stripped)
            return _orders_from_json(records, base_url, bench_code, state_code)
        except Exception:
            pass  # Fall through to HTML parsing

    # HTML table fallback
    return _parse_orders_html(raw, base_url)


def _orders_from_json(
    records: list[dict],
    base_url: str,
    bench_code: str,
    state_code: str,
) -> list[CaseOrder]:
    """Build CaseOrder list from showRecords JSON records."""
    results = []
    for rec in records:
        orderurlpath = rec.get("orderurlpath", "")
        if not orderurlpath:
            continue

        cino = rec.get("cino", "")
        type_name = rec.get("type_name", "")
        case_no2 = str(rec.get("case_no2", ""))
        case_year = str(rec.get("case_year", ""))
        caseno = f"{type_name}/{case_no2}/{case_year}" if type_name else ""

        # orderurlpath is already URL-encoded from the server — use as-is
        pdf_url = (
            f"{base_url}/cases/display_pdf.php"
            f"?filename={orderurlpath}"
            f"&caseno={caseno}"
            f"&cCode={bench_code}"
            f"&appFlag=web"
            f"&normal_v=1"
            f"&cino={cino}"
            f"&state_code={state_code}"
            f"&flag=nojudgement"
        )

        results.append(
            CaseOrder(
                order_date=_parse_date("") or date.today(),
                order_type="Order",
                judge="",
                pdf_url=pdf_url,
            )
        )

    return results


def _parse_orders_html(html: str, base_url: str = "") -> list[CaseOrder]:
    """Parse orders from an HTML table (legacy format)."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="orderTable") or soup.find("table")
    if not table:
        return []

    results = []
    rows = table.find_all("tr")[1:]

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 5:
            continue

        order_date = _parse_date(cols[1].get_text())
        if not order_date:
            continue

        order_type = _clean_text(cols[2].get_text())
        judge = _clean_text(cols[3].get_text())

        link = cols[4].find("a")
        pdf_url = ""
        if link and link.get("href"):
            href = link["href"]
            if href.startswith("/"):
                pdf_url = base_url + href
            else:
                pdf_url = href

        results.append(
            CaseOrder(
                order_date=order_date,
                order_type=order_type,
                judge=judge,
                pdf_url=pdf_url,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Cause list — HTML table
# ---------------------------------------------------------------------------


def parse_cause_list(html: str, base_url: str = "") -> list[CauseListPDF]:
    """Parse cause list response from HC Services.

    The portal returns a table with columns:
    Sr No | Bench | Cause List Type | View Causelist (PDF link)

    This is a meta-table listing PDF links per bench, not individual cases.

    Args:
        html: Raw HTML response from showCauseList.
        base_url: Base URL for resolving relative PDF links.

    Returns:
        List of CauseListPDF objects with bench info and PDF URLs.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_="causelistTbl") or soup.find("table")
    if not table:
        return []

    results = []
    rows = table.find_all("tr")[1:]  # Skip header

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue

        serial = _clean_text(cols[0].get_text())
        bench = _clean_text(cols[1].get_text())
        cause_list_type = _clean_text(cols[2].get_text())

        # Extract PDF link from the "View" column
        link = cols[3].find("a")
        pdf_url = ""
        if link and link.get("href"):
            href = link["href"].strip()
            if href.startswith("http"):
                pdf_url = href
            elif base_url:
                # hrefs like "cases/display_causelist_pdf.php?..." are relative
                # to the /hcservices root (the main page), not cases_qry/
                pdf_url = f"{base_url}/{href.lstrip('/')}"
            else:
                pdf_url = href

        try:
            serial_num = int(serial)
        except ValueError:
            serial_num = 0

        results.append(
            CauseListPDF(
                serial_number=serial_num,
                bench=bench,
                cause_list_type=cause_list_type,
                pdf_url=pdf_url,
            )
        )

    return results
