"""Parsers for Calcutta High Court portal responses.

The search endpoint returns JSON with case metadata and an HTML fragment
containing order rows. Each row has: order number, date, judge, type
(with neutral citation), and a show_order() JS call for PDF resolution.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from bharat_courts.models import CaseOrder

logger = logging.getLogger(__name__)


def _parse_date(text: str) -> date | None:
    """Parse DD-MM-YYYY date string."""
    text = text.strip()
    if not text:
        return None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _clean_html(text: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    clean = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", clean).strip()


def parse_search_response(raw: str) -> dict:
    """Parse the JSON response from /order_judgment_search.

    Returns a dict with keys:
        cino, full_case_num, cause_title, orders (list of order dicts)

    Each order dict has: order_num, order_date, judge, order_type,
        neutral_citation, order_data (for show_pdf call)
    """
    data = json.loads(raw)
    if isinstance(data, str):
        data = json.loads(data)

    result = {
        "cino": data.get("cino", ""),
        "full_case_num": data.get("full_Case_num", ""),
        "cause_title": _clean_html(data.get("cause_title", "")),
        "orders": [],
    }

    html = data.get("list", "")
    if not html:
        return result

    result["orders"] = _parse_order_rows(html)
    return result


def _parse_order_rows(html: str) -> list[dict]:
    """Parse order rows from the HTML table fragment.

    Each <tr> has 5 <td>s:
    1. Order number
    2. Date (DD-MM-YYYY)
    3. Judge name
    4. Type + neutral citation
    5. View Order button with show_order() call
    """
    orders = []
    # Match each <tr>...</tr>
    for tr_match in re.finditer(r"<tr>(.*?)<\/tr>", html, re.DOTALL | re.IGNORECASE):
        tr = tr_match.group(1)
        tds = re.findall(r"<td>(.*?)<\/td>", tr, re.DOTALL | re.IGNORECASE)
        if len(tds) < 5:
            continue

        order_num = _clean_html(tds[0])
        order_date = _clean_html(tds[1])
        judge = _clean_html(tds[2])

        # Type cell contains order type + optional neutral citation
        type_cell = tds[3]
        order_type = ""
        neutral_citation = ""

        # Extract neutral citation
        cit_match = re.search(
            r"Neutral Citation:.*?(\d{4}:[A-Z]+-[A-Z]+:\d+)", type_cell, re.IGNORECASE
        )
        if cit_match:
            neutral_citation = cit_match.group(1)

        # Order type is the text before <br> or <small>
        type_text = re.split(r"<br|<small", type_cell, maxsplit=1)[0]
        order_type = _clean_html(type_text)

        # Extract show_order() parameter
        order_data = ""
        od_match = re.search(r'show_order\([\\]*"([^"\\]+)', tds[4])
        if od_match:
            order_data = od_match.group(1)

        orders.append({
            "order_num": order_num,
            "order_date": order_date,
            "judge": judge,
            "order_type": order_type,
            "neutral_citation": neutral_citation,
            "order_data": order_data,
        })

    return orders


def to_case_orders(parsed: dict, pdf_urls: dict[str, str] | None = None) -> list[CaseOrder]:
    """Convert parsed response to CaseOrder models.

    Args:
        parsed: Output from parse_search_response().
        pdf_urls: Optional mapping of order_data → PDF URL (from show_pdf calls).
    """
    pdf_urls = pdf_urls or {}
    results = []

    for order in parsed.get("orders", []):
        order_date = _parse_date(order["order_date"])
        if not order_date:
            logger.warning("Skipping order with unparseable date: %s", order["order_date"])
            continue

        results.append(
            CaseOrder(
                order_date=order_date,
                order_type=order.get("order_type", "Order"),
                judge=order.get("judge", ""),
                neutral_citation=order.get("neutral_citation", ""),
                pdf_url=pdf_urls.get(order.get("order_data", ""), ""),
            )
        )

    return results
