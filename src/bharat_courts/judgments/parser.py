"""BS4 HTML parsers for Judgment Search portal responses."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from bharat_courts.models import JudgmentResult, SearchResult

logger = logging.getLogger(__name__)

DATE_FORMAT = "%d-%m-%Y"


def _parse_date(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, DATE_FORMAT).date()
    except ValueError:
        logger.debug("Could not parse date: %s", text)
        return None


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_judges(text: str) -> list[str]:
    """Parse judge names from comma/and-separated string."""
    text = _clean_text(text)
    # Remove "Hon'ble" prefix
    text = re.sub(r"Hon'?ble\s+", "", text, flags=re.IGNORECASE)
    # Split on comma or " and "
    parts = re.split(r",\s*|\s+and\s+", text, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


def _extract_title_and_case(cell: Tag) -> tuple[str, str]:
    """Extract title and case number from case details cell.

    The title is in the first <strong> (not .caseDetailsTD).
    """
    strong = cell.find("strong", class_=lambda c: c != "caseDetailsTD")
    title = _clean_text(strong.get_text()) if strong else ""

    # Case number is typically after the <br> tag but before metadata
    full_text = _clean_text(cell.get_text())
    # Remove metadata block text if present
    metadata_block = cell.find("strong", class_="caseDetailsTD")
    if metadata_block:
        metadata_text = _clean_text(metadata_block.get_text())
        full_text = full_text.replace(metadata_text, "")
    case_number = full_text.replace(title, "").strip()
    return title, case_number


def _extract_case_metadata(cell: Tag) -> dict[str, str]:
    """Extract metadata from <strong class="caseDetailsTD"> blocks.

    The portal uses <span>Label</span><font>Value</font> pairs.
    Returns a dict of label->value. Empty dict if no metadata block.
    """
    block = cell.find("strong", class_="caseDetailsTD")
    if not block:
        return {}

    metadata: dict[str, str] = {}
    spans = block.find_all("span")
    for span in spans:
        label = _clean_text(span.get_text())
        if not label:
            continue
        # Value is in the next <font> sibling
        font = span.find_next_sibling("font")
        if font:
            metadata[label] = _clean_text(font.get_text())
    return metadata


def _parse_total_count(soup: BeautifulSoup) -> int:
    """Extract total result count from pagination text."""
    pagination = soup.find("div", class_="pagination") or soup.find(
        "span", string=re.compile(r"of \d+")
    )
    if not pagination:
        return 0
    text = pagination.get_text()
    match = re.search(r"of\s+(\d+)", text)
    return int(match.group(1)) if match else 0


def _has_next_page(soup: BeautifulSoup) -> bool:
    """Check if there's a next page link."""
    next_link = soup.find("a", class_="next") or soup.find(
        "a", string=re.compile(r"Next", re.IGNORECASE)
    )
    return next_link is not None


def parse_judgment_search(html: str, base_url: str = "", page: int = 1) -> SearchResult:
    """Parse judgment search results page into SearchResult."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="resultTable") or soup.find("table")
    if not table:
        return SearchResult()

    judgments: list[JudgmentResult] = []
    rows = table.find_all("tr")[1:]  # Skip header

    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 7:
            continue

        title, case_number = _extract_title_and_case(cols[2])
        metadata = _extract_case_metadata(cols[2])
        court_name = _clean_text(cols[3].get_text())
        judges = _parse_judges(cols[4].get_text())
        judgment_date = _parse_date(cols[5].get_text())

        # Extract PDF URL
        link = cols[6].find("a")
        pdf_url = ""
        if link and link.get("href"):
            href = link["href"]
            if href.startswith("/"):
                pdf_url = base_url + href
            else:
                pdf_url = href

        bench_type = ""
        if len(judges) >= 3:
            bench_type = "Full Bench"
        elif len(judges) == 2:
            bench_type = "Division Bench"
        elif len(judges) == 1:
            bench_type = "Single Bench"

        # Promote CNR Number to source_id if present
        source_id = metadata.pop("CNR Number", "")

        judgments.append(
            JudgmentResult(
                title=title,
                court_name=court_name,
                case_number=case_number,
                judgment_date=judgment_date,
                judges=judges,
                pdf_url=pdf_url,
                bench_type=bench_type,
                source_url=pdf_url,
                source_id=source_id,
                metadata=metadata,
            )
        )

    total_count = _parse_total_count(soup)
    has_next = _has_next_page(soup)

    return SearchResult(
        items=judgments,
        total_count=total_count if total_count else len(judgments),
        page=page,
        page_size=len(judgments),
        has_next=has_next,
    )
