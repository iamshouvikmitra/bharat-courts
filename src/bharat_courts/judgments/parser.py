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
    """Extract title and case number from case details cell."""
    strong = cell.find("strong")
    title = _clean_text(strong.get_text()) if strong else ""

    # Case number is typically after the <br> tag
    full_text = _clean_text(cell.get_text())
    case_number = full_text.replace(title, "").strip()
    return title, case_number


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
