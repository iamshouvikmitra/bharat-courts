"""BS4 HTML parsers for Supreme Court of India website."""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from bharat_courts.models import JudgmentResult

logger = logging.getLogger(__name__)


def _parse_date(text: str, fmt: str = "%d-%m-%Y") -> date | None:
    text = text.strip()
    if not text:
        return None
    # Try multiple date formats used by SCI
    for f in (fmt, "%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, f).date()
        except ValueError:
            continue
    logger.debug("Could not parse date: %s", text)
    return None


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text.strip())


def _parse_judges(text: str) -> list[str]:
    text = _clean_text(text)
    text = re.sub(r"Hon'?ble\s+", "", text, flags=re.IGNORECASE)
    parts = re.split(r",\s*|\s+and\s+", text, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


def parse_judgment_list(
    html: str, base_url: str = "https://main.sci.gov.in"
) -> list[JudgmentResult]:
    """Parse SCI judgment listing page.

    The SCI website lists judgments in a table with columns for
    date, case number, parties, judges, and PDF download link.
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[JudgmentResult] = []

    # SCI uses various table structures; try to find judgment entries
    # Look for tables with PDF links
    tables = soup.find_all("table")

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 3:
                continue

            # Look for PDF links in any column
            pdf_link = row.find("a", href=re.compile(r"\.pdf", re.IGNORECASE))
            if not pdf_link:
                continue

            href = pdf_link["href"]
            if href.startswith("/"):
                pdf_url = base_url + href
            elif not href.startswith("http"):
                pdf_url = base_url + "/" + href
            else:
                pdf_url = href

            # Extract available metadata from columns
            texts = [_clean_text(col.get_text()) for col in cols]

            # Heuristic: find date-like and title-like columns
            judgment_date = None
            title = ""
            case_number = ""

            for text in texts:
                if not judgment_date:
                    judgment_date = _parse_date(text)
                elif not title:
                    title = text
                elif not case_number:
                    case_number = text

            if not title:
                title = _clean_text(pdf_link.get_text()) or pdf_url.split("/")[-1]

            results.append(
                JudgmentResult(
                    title=title,
                    court_name="Supreme Court of India",
                    case_number=case_number,
                    judgment_date=judgment_date,
                    pdf_url=pdf_url,
                    source_url=pdf_url,
                    source_id=href,
                )
            )

    logger.info("Parsed %d SCI judgments", len(results))
    return results
