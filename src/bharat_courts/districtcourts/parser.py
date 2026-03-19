"""Parsers for District Courts portal responses.

The portal returns JSON envelopes containing:
- Pre-rendered HTML fragments for search results (party_data, case_data, etc.)
- HTML <option> tags for cascade dropdown data (dist_list, complex_list, etc.)
- A rotating app_token in every response

Unlike HC Services (which returns JSON case arrays), district court search
results are HTML tables that must be parsed with BeautifulSoup.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from bharat_courts.models import CaseInfo, CaseOrder, CauseListEntry

logger = logging.getLogger(__name__)

DATE_FORMAT = "%d-%m-%Y"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


class CaptchaError(Exception):
    """Raised when the server rejects the CAPTCHA."""


class ServerError(Exception):
    """Raised on a server-side error response."""


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
# AJAX response envelope
# ---------------------------------------------------------------------------


def parse_ajax_response(raw: str) -> dict:
    """Parse the JSON envelope from an AJAX response.

    The portal returns JSON like:
        {"status": 1, "app_token": "xxx", "party_data": "<table>...</table>"}
    or on captcha failure:
        {"status": 0, "app_token": "xxx", "div_captcha": "..."}

    Returns:
        Parsed dict with all response fields.

    Raises:
        CaptchaError: If status is 0 (CAPTCHA failed).
        ServerError: If errormsg is present.
    """
    text = raw.strip().lstrip("\ufeff")

    # Handle responses split by #####  (error format)
    if "#####" in text:
        parts = text.split("#####")
        error_msg = parts[0].strip()
        if error_msg:
            raise ServerError(error_msg)

    try:
        data = json.loads(text, strict=False)
    except json.JSONDecodeError:
        # Some responses are HTML, not JSON
        logger.warning("Non-JSON response: %s...", text[:200])
        return {"status": 0, "raw": text}

    if not isinstance(data, dict):
        return {"status": 0, "raw": text}

    # Check for errors
    errormsg = data.get("errormsg")
    if errormsg:
        raise ServerError(errormsg)

    # CAPTCHA failure
    status = data.get("status")
    if status == 0 or status == "0":
        raise CaptchaError("CAPTCHA validation failed")

    return data


# ---------------------------------------------------------------------------
# Cascade dropdown parsers
# ---------------------------------------------------------------------------


def parse_option_tags(html: str) -> dict[str, str]:
    """Parse HTML <option> tags into a {value: text} dict.

    The portal returns cascade dropdown data as HTML option fragments:
        <option value="1">Patna</option><option value="2">Gaya</option>

    Filters out placeholder options (value="0" or empty, text contains "Select").
    """
    soup = BeautifulSoup(html, "lxml")
    options = soup.find_all("option")
    result = {}
    for opt in options:
        value = opt.get("value", "").strip()
        text = _clean_text(opt.get_text())
        if not value or value == "0" or "select" in text.lower():
            continue
        result[value] = text
    return result


def parse_complex_value(value: str) -> tuple[str, list[str], bool]:
    """Parse a court complex dropdown value.

    Format: ``complex_code@est_codes@flag``
    Example: ``1080010@2,3,4@Y``

    Returns:
        (complex_code, [est_code, ...], needs_establishment)
        where needs_establishment is True when flag == 'Y'.
    """
    parts = value.split("@")
    complex_code = parts[0] if parts else value
    est_codes = parts[1].split(",") if len(parts) > 1 and parts[1] else []
    needs_est = parts[2] == "Y" if len(parts) > 2 else False
    return complex_code, est_codes, needs_est


# ---------------------------------------------------------------------------
# Case status HTML parser
# ---------------------------------------------------------------------------


def _extract_parties(cell: Tag) -> tuple[str, str]:
    """Extract petitioner and respondent from a parties cell.

    The portal uses several formats:
    - ``<strong>Pet</strong><br>vs<br><strong>Resp</strong>`` (test fixtures)
    - ``Pet Name<br>Vs</br>Resp Name`` (live portal, note malformed </br>)
    - ``PetVsResp`` (concatenated text after tag stripping)
    """
    strongs = cell.find_all("strong")
    if len(strongs) >= 2:
        return _clean_text(strongs[0].get_text()), _clean_text(strongs[1].get_text())

    # Try splitting on <br> tags first — the live portal uses <br>Vs</br>
    # which means after get_text(), "Vs" may or may not have spaces.
    text = _clean_text(cell.get_text())
    # Split on Vs/vs with or without word boundaries (handles "MahtoVsState")
    parts = re.split(r"Vs\.?|vs\.?|\bvs?\b", text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()

    return text, ""


def _extract_cnr(row: Tag) -> str:
    """Extract CNR number from a table row.

    The portal puts CNR in onclick handlers like:
    viewHistory(case_id, 'BRPA010216322024', ...)
    or showCaseDetails('BHAR010001232024')
    """
    for link in row.find_all("a"):
        onclick = link.get("onclick", "")
        if not onclick:
            # Also check aria-label for embedded data
            continue
        # viewHistory pattern: second argument is CNR (quoted)
        cnr_match = re.search(r"'([A-Z]{4}\d{12,})'", onclick)
        if cnr_match:
            return cnr_match.group(1)
        # viewHistory pattern: second argument is CNR (unquoted comma-sep)
        vh_match = re.search(r"viewHistory\([^,]+,'([A-Z]{4}\d{12,})'", onclick)
        if vh_match:
            return vh_match.group(1)
    return ""


def parse_case_status_html(html: str) -> list[CaseInfo]:
    """Parse case status results from an HTML table.

    The district court portal returns results in two formats:

    **Live format (4 columns)**:
    Sr No | Case Type/Case Number/Case Year | Petitioner Vs Respondent | View

    **Extended format (7+ columns, used in some responses)**:
    Sr No | Case Number | Parties | Advocate | Filing Date | Reg Date | Status

    The parser auto-detects the format based on column count.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    results = []
    rows = table.find_all("tr")

    for row in rows:
        # Skip header rows and court name group rows (th with colspan)
        if row.find("th"):
            continue

        cols = row.find_all("td")
        if len(cols) < 3:
            continue

        # Detect format by column count
        if len(cols) <= 4:
            # Live format: Sr No | Case Number | Parties | View
            case_number = _clean_text(cols[1].get_text())
            petitioner, respondent = _extract_parties(cols[2])
            cnr = _extract_cnr(row)
            reg_date = None
            status = ""
            next_hearing = None
        else:
            # Extended format: Sr No | Case | Parties | Advocate | Filing | Reg | Status | Next
            case_number = _clean_text(cols[1].get_text())
            petitioner, respondent = _extract_parties(cols[2])
            cnr = _extract_cnr(row)
            reg_date = _parse_date(cols[5].get_text()) if len(cols) > 5 else None
            status = _clean_text(cols[6].get_text()) if len(cols) > 6 else ""
            next_hearing = _parse_date(cols[7].get_text()) if len(cols) > 7 else None

        results.append(
            CaseInfo(
                case_number=case_number,
                case_type=case_number.split("/")[0] if "/" in case_number else "",
                cnr_number=cnr,
                petitioner=petitioner,
                respondent=respondent,
                registration_date=reg_date,
                status=status,
                next_hearing_date=next_hearing,
            )
        )

    return results


# ---------------------------------------------------------------------------
# Court orders HTML parser
# ---------------------------------------------------------------------------


def parse_court_orders_html(html: str, base_url: str = "") -> list[CaseOrder]:
    """Parse court orders from an HTML table.

    Expected columns: Sr No | Order Date | Order Type | Judge | Order (PDF link)
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    results = []
    rows = table.find_all("tr")[1:]

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue

        order_date = _parse_date(cols[1].get_text())
        if not order_date:
            continue

        order_type = _clean_text(cols[2].get_text())
        judge = _clean_text(cols[3].get_text())

        pdf_url = ""
        if len(cols) > 4:
            link = cols[4].find("a")
            if link and link.get("href"):
                href = link["href"].strip()
                if href.startswith("http"):
                    pdf_url = href
                elif href.startswith("/"):
                    pdf_url = base_url + href if base_url else href
                else:
                    pdf_url = f"{base_url}/{href}" if base_url else href

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
# Cause list HTML parser
# ---------------------------------------------------------------------------


def parse_cause_list_html(html: str) -> list[CauseListEntry]:
    """Parse cause list from an HTML table.

    District court cause lists return individual case entries (not PDF links).
    Expected columns: Sr No | Case Number | Parties | Advocate | Court No | Judge
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    results = []
    rows = table.find_all("tr")[1:]

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 4:
            continue

        try:
            serial = int(_clean_text(cols[0].get_text()))
        except ValueError:
            serial = 0

        case_number = _clean_text(cols[1].get_text())
        petitioner, respondent = _extract_parties(cols[2])

        advocate = _clean_text(cols[3].get_text()) if len(cols) > 3 else ""
        court_no = _clean_text(cols[4].get_text()) if len(cols) > 4 else ""
        judge = _clean_text(cols[5].get_text()) if len(cols) > 5 else ""

        results.append(
            CauseListEntry(
                serial_number=serial,
                case_number=case_number,
                case_type=case_number.split("/")[0] if "/" in case_number else "",
                petitioner=petitioner,
                respondent=respondent,
                advocate_petitioner=advocate,
                court_number=court_no,
                judge=judge,
            )
        )

    return results
