"""Parsers for the Judgment Search portal's DataTables AJAX response.

The portal's search endpoint (``?p=pdf_search/home``) returns JSON shaped
roughly as::

    {
      "reportrow": {
        "iTotalRecords": 54122,
        "iTotalDisplayRecords": 54122,
        "aaData": [
          [1, "<button onclick=open_pdf('0','','court/.../X.pdf#...')>...</button>..."],
          ...
        ]
      },
      "total": "54,122",
      "app_token": "..."
    }

Each ``aaData`` row is a ``[serial, html_blob]`` pair. The HTML blob packs
the case number, parties, judges, an excerpt, and a metadata line with
CNR / dates / disposal / court name. We extract these into
:class:`JudgmentResult`. The PDF's relative path lives in the
``open_pdf(...)`` ``onclick`` and is stored in ``pdf_url`` for the client
to resolve later via ``openpdfcaptcha``.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from bharat_courts.models import JudgmentResult, SearchResult

logger = logging.getLogger(__name__)

DATE_FORMAT = "%d-%m-%Y"

_OPEN_PDF_RE = re.compile(r"open_pdf\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']+)'")


def _parse_date(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
        return None


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _split_parties(case_label: str) -> tuple[str, str, str]:
    """Pull case number + parties out of ``"<case_no> of <pet> Vs <resp>"``.

    Returns ``(case_number, petitioner, respondent)``.
    """
    text = _clean(case_label)
    # The "of" separator is consistent across rows; "Vs"/"VS"/"vs" varies.
    m = re.match(r"^(.+?)\s+of\s+(.+)$", text)
    if not m:
        return text, "", ""
    case_no = m.group(1).strip()
    parties = m.group(2)
    parts = re.split(r"\s+(?:Vs\.?|VS\.?|vs\.?|V/S)\s+", parties, maxsplit=1)
    if len(parts) == 2:
        return case_no, parts[0].strip(), parts[1].strip()
    return case_no, parties.strip(), ""


def _parse_metadata_block(soup: BeautifulSoup) -> dict[str, str]:
    """Extract ``<span>Label :</span><font>Value</font>`` pairs from the
    ``<strong class='caseDetailsTD'>`` block at the end of each row."""
    block = soup.find("strong", class_="caseDetailsTD")
    if not block:
        return {}
    pairs: dict[str, str] = {}
    for span in block.find_all("span"):
        # Labels look like " | Date of registration :" — strip the
        # ``|`` separator the portal uses and the trailing colon.
        label = _clean(span.get_text()).lstrip("|").strip().rstrip(":").strip()
        if not label:
            continue
        font = span.find_next_sibling("font")
        if font is None:
            continue
        pairs[label] = _clean(font.get_text())
    # The "Court : <name>" line is often rendered as a plain <span> with the
    # value following inline — pick it up from the block text if missing.
    if "Court" not in pairs:
        m = re.search(r"Court\s*:\s*([^\n<]+)", block.get_text())
        if m:
            pairs["Court"] = _clean(m.group(1))
    return pairs


def _parse_row_html(blob: str) -> JudgmentResult | None:
    """Parse one ``aaData[i][1]`` HTML blob into a JudgmentResult."""
    soup = BeautifulSoup(blob, "lxml")

    # Path from the open_pdf(...) onclick.
    pdf_path = ""
    for tag in soup.find_all(onclick=True):
        m = _OPEN_PDF_RE.search(tag.get("onclick", ""))
        if m:
            pdf_path = m.group(3)
            break
    if not pdf_path:
        # Fall back to scanning the raw blob in case the onclick is elsewhere.
        m = _OPEN_PDF_RE.search(blob)
        if m:
            pdf_path = m.group(3)

    # The case label is the visible <button>/<font> text, e.g.
    # "CRMP/1144/2026 of AKASH TIWARI Vs STATE OF CHHATTISGARH".
    button = soup.find("button")
    case_label_text = _clean(button.get_text()) if button else ""
    case_no, pet, resp = _split_parties(case_label_text)

    # Judges: the first <strong> that starts with "Judge :".
    judges: list[str] = []
    for strong in soup.find_all("strong"):
        text = _clean(strong.get_text())
        if text.lower().startswith("judge"):
            raw = re.sub(r"^Judge\s*:\s*", "", text, flags=re.IGNORECASE)
            raw = re.sub(r"Hon'?ble\s+", "", raw, flags=re.IGNORECASE)
            judges = [p.strip() for p in re.split(r",\s*|\s+and\s+", raw) if p.strip()]
            break

    metadata = _parse_metadata_block(soup)
    cnr = metadata.pop("CNR", "")
    reg_date = _parse_date(metadata.pop("Date of registration", ""))
    judgment_date = _parse_date(metadata.pop("Decision Date", ""))
    disposal = metadata.pop("Disposal Nature", "")
    court_name = metadata.pop("Court", "")

    if disposal:
        metadata["disposal_nature"] = disposal
    if reg_date:
        metadata["registration_date"] = reg_date.isoformat()

    bench_type = ""
    if len(judges) >= 3:
        bench_type = "Full Bench"
    elif len(judges) == 2:
        bench_type = "Division Bench"
    elif len(judges) == 1:
        bench_type = "Single Bench"

    title = f"{pet} v. {resp}".strip(" v.") if pet else case_label_text

    return JudgmentResult(
        title=title,
        court_name=court_name,
        case_number=case_no,
        judgment_date=judgment_date,
        judges=judges,
        pdf_url=pdf_path,  # raw path; client.download_pdf() resolves it
        bench_type=bench_type,
        source_id=cnr,
        metadata=metadata,
    )


def parse_search_response(
    payload: dict,
    *,
    page: int,
    page_size: int,
) -> SearchResult:
    """Parse the JSON payload from ``?p=pdf_search/home`` into a SearchResult."""
    rr = payload.get("reportrow") or {}
    total = rr.get("iTotalDisplayRecords") or rr.get("iTotalRecords") or 0
    try:
        total = int(total)
    except (TypeError, ValueError):
        total = 0

    items: list[JudgmentResult] = []
    for row in rr.get("aaData") or []:
        if not isinstance(row, list) or len(row) < 2 or not isinstance(row[1], str):
            continue
        parsed = _parse_row_html(row[1])
        if parsed:
            items.append(parsed)

    has_next = page * page_size < total
    return SearchResult(
        items=items,
        total_count=total,
        page=page,
        page_size=page_size,
        has_next=has_next,
    )
