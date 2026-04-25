"""Parsers for the Supreme Court of India site (``www.sci.gov.in``).

The homepage embeds the most recent judgments as plain anchors::

    <a href="https://www.sci.gov.in/view-pdf/?diary_no=94392025&type=j
            &order_date=2026-04-24&from=latest_judgements_order">
      VINAY RAGHUNATH DESHMUKH VS. NATWARLAL SHAMJI GADA - C.A. No. 6677/2026
      - Diary Number 9439 / 2025 - 24-Apr-2026
      <div ...>(Uploaded On 24-04-2026 17:22:34)</div>
    </a>

We pull the diary number / order date / type from the query string and the
parties / case number / decision date from the visible text. The viewer
URL stays in ``source_url``; ``pdf_url`` carries the directly-downloadable
``/sci-get-pdf/?...`` URL (same params).
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from bharat_courts.models import JudgmentResult

logger = logging.getLogger(__name__)

VIEW_PDF_PATH = "/view-pdf/"
GET_PDF_PATH = "/sci-get-pdf/"


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _parse_decision_date(text: str) -> date | None:
    """Parse "24-Apr-2026" or "24-04-2026" into a date."""
    text = text.strip()
    if not text:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _split_parties(text: str) -> tuple[str, str]:
    """Split "PETITIONER VS. RESPONDENT" on a case-insensitive ``Vs.``."""
    parts = re.split(r"\s+(?:Vs\.?|VS\.?|vs\.?)\s+", text, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return text.strip(), ""


def _build_pdf_url(view_url: str, base_url: str) -> str:
    """Replace the ``/view-pdf/`` path with ``/sci-get-pdf/`` while
    preserving the query string. The new URL is the iframe ``src`` the
    portal viewer uses internally and is directly downloadable."""
    if VIEW_PDF_PATH not in view_url:
        return view_url
    return view_url.replace(VIEW_PDF_PATH, GET_PDF_PATH, 1)


def parse_recent_judgments(
    html_text: str,
    *,
    base_url: str = "https://www.sci.gov.in",
) -> list[JudgmentResult]:
    """Parse the homepage of ``www.sci.gov.in`` into JudgmentResult objects.

    Returns judgments listed in the "Latest Judgements / Orders" tab.
    Order dates / case numbers / parties / diary numbers are extracted
    from each anchor's text and href.
    """
    soup = BeautifulSoup(html_text, "lxml")
    results: list[JudgmentResult] = []

    anchors = soup.select('a[href*="view-pdf/?diary_no="][href*="from=latest_judgements_order"]')
    for a in anchors:
        href = a.get("href", "")
        if not href:
            continue

        params = parse_qs(urlparse(href).query)
        diary_no = (params.get("diary_no") or [""])[0]
        url_type = (params.get("type") or [""])[0]
        url_order_date = (params.get("order_date") or [""])[0]

        # Pull the visible main label out of the anchor, ignoring the
        # nested <div>(Uploaded On ...)</div> tail.
        for div in a.find_all("div"):
            div.extract()
        label = _clean(a.get_text())

        # Label shape: "PARTIES - CASE_NO - Diary Number X / Y - DD-MMM-YYYY".
        # Split on " - " but not on hyphens inside CASE_NO ("C.A. No.").
        parts = [p.strip() for p in re.split(r"\s+-\s+", label) if p.strip()]
        parties_part = parts[0] if parts else ""
        case_number = parts[1] if len(parts) > 1 else ""
        # The "Diary Number ... / ..." segment is parts[2]; we already have
        # the canonical diary_no from the URL so we don't re-extract.
        decision_date_text = parts[3] if len(parts) > 3 else url_order_date

        petitioner, respondent = _split_parties(parties_part)
        decision_date = _parse_decision_date(decision_date_text) or _parse_decision_date(
            url_order_date
        )

        title = parties_part if parties_part else case_number or diary_no

        view_url = href if href.startswith("http") else base_url + href
        pdf_url = _build_pdf_url(view_url, base_url)

        results.append(
            JudgmentResult(
                title=title,
                court_name="Supreme Court of India",
                case_number=case_number,
                judgment_date=decision_date,
                pdf_url=pdf_url,
                source_url=view_url,
                source_id=diary_no,
                metadata={
                    "petitioner": petitioner,
                    "respondent": respondent,
                    "type": url_type,  # "j" = judgment, "o" = order
                    "from": "latest_judgements_order",
                },
            )
        )

    logger.info("Parsed %d SCI recent judgments", len(results))
    return results
