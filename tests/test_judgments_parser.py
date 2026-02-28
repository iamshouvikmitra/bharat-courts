"""Tests for Judgment Search portal parsers."""

from datetime import date

from bharat_courts.judgments.parser import parse_judgment_search
from bharat_courts.models import JudgmentResult


def test_parse_judgment_search(judgments_search_html):
    result = parse_judgment_search(
        judgments_search_html, base_url="https://judgments.ecourts.gov.in"
    )
    assert len(result.items) == 2
    assert result.total_count == 45
    assert result.has_next is True

    j1 = result.items[0]
    assert isinstance(j1, JudgmentResult)
    assert j1.title == "ABC Industries vs Union of India"
    assert j1.court_name == "Delhi High Court"
    assert j1.judgment_date == date(2024, 2, 15)
    assert j1.pdf_url.endswith("judgment_001.pdf")

    j2 = result.items[1]
    assert j2.title == "State vs XYZ Enterprises"


def test_parse_judgment_search_empty():
    result = parse_judgment_search("<html></html>")
    assert len(result.items) == 0
    assert result.total_count == 0
