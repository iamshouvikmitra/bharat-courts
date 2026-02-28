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

import json
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from bharat_courts.models import CaseInfo, CaseOrder, CauseListPDF

logger = logging.getLogger(__name__)

DATE_FORMAT = "%d-%m-%Y"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _parse_date(text: str) -> date | None:
    """Parse DD-MM-YYYY date string."""
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
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


def _parse_json_envelope(raw: str) -> tuple[list[dict], int]:
    """Parse the outer JSON envelope from showRecords responses.

    Returns:
        (records_list, total_count).

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
        total = int(data.get("totRecords", 0))

        if isinstance(con, list) and con:
            # con is a list of JSON-encoded strings
            inner = con[0]
            if isinstance(inner, str):
                try:
                    records = json.loads(inner, strict=False)
                except json.JSONDecodeError:
                    logger.warning("Could not parse inner con JSON")
                    return [], total
            elif isinstance(inner, dict):
                records = [inner]
            else:
                records = []
            return records if isinstance(records, list) else [], total
        return [], total

    # Not JSON at all
    return [], 0


# ---------------------------------------------------------------------------
# Case status — JSON-based
# ---------------------------------------------------------------------------


def parse_case_status(raw: str) -> list[CaseInfo]:
    """Parse case status search results (JSON response from showRecords).

    The response envelope is ``{"con": ["[{...}]"], "totRecords": N}``.
    Each record in the inner array has at least:
    ``cino``, ``case_no``, ``case_no2``, ``case_type``, ``case_year``,
    ``pet_name``, ``res_name``, ``orderurlpath``.
    """
    # Fall back to HTML parsing if the response is an HTML table
    if "<table" in raw.lower():
        return _parse_case_status_html(raw)

    records, total = _parse_json_envelope(raw)
    results = []
    for rec in records:
        case_type_code = str(rec.get("case_type", ""))
        case_no = str(rec.get("case_no2", ""))
        case_year = str(rec.get("case_year", ""))
        case_number_display = f"{case_no}/{case_year}" if case_no and case_year else ""

        results.append(
            CaseInfo(
                case_number=case_number_display,
                case_type=case_type_code,
                cnr_number=rec.get("cino", ""),
                petitioner=rec.get("pet_name") or "",
                respondent=rec.get("res_name") or "",
                status=rec.get("status_name") or rec.get("status") or "",
                registration_date=_parse_date(rec.get("reg_date", "")),
                filing_number=rec.get("case_no", ""),
            )
        )

    logger.info("Parsed %d/%d case status records", len(results), total)
    return results


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


def parse_orders(html: str, base_url: str = "") -> list[CaseOrder]:
    """Parse orders table response."""
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
                pdf_url = f"{base_url}/cases_qry/{href}"
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
