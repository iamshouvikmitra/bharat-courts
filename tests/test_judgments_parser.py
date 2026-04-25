"""Tests for the Judgment Search portal JSON parser."""

from datetime import date

from bharat_courts.judgments.parser import _split_parties, parse_search_response
from bharat_courts.models import JudgmentResult


def test_split_parties_with_vs():
    case, pet, resp = _split_parties("WP(C)/1/2024 of ABC INDUSTRIES Vs UNION OF INDIA")
    assert case == "WP(C)/1/2024"
    assert pet == "ABC INDUSTRIES"
    assert resp == "UNION OF INDIA"


def test_split_parties_with_dotted_vs():
    case, pet, resp = _split_parties("X/1/2024 of A Vs. B")
    assert case == "X/1/2024"
    assert pet == "A"
    assert resp == "B"


def test_split_parties_no_match():
    case, pet, resp = _split_parties("just some text")
    assert case == "just some text"
    assert pet == ""
    assert resp == ""


def test_parse_search_response(judgments_search_response):
    sr = parse_search_response(judgments_search_response, page=1, page_size=10)

    assert sr.total_count == 54122
    assert sr.page == 1
    assert sr.page_size == 10
    assert sr.has_next is True
    assert len(sr.items) == 2

    j1 = sr.items[0]
    assert isinstance(j1, JudgmentResult)
    assert j1.case_number == "CRMP/1144/2026"
    assert "AKASH TIWARI" in j1.title
    assert "STATE OF CHHATTISGARH" in j1.title
    assert j1.court_name == "High Court Of Chhattisgarh"
    assert j1.source_id == "CGHC010160032026"
    assert j1.judgment_date == date(2026, 4, 22)
    assert j1.metadata["registration_date"] == "2026-04-21"
    assert j1.metadata["disposal_nature"] == "ALLOWED"
    assert j1.bench_type == "Division Bench"
    assert len(j1.judges) == 2
    # PDF path stripped of fragment? No — the parser stores the raw path; the
    # client strips it before talking to openpdfcaptcha.
    assert j1.pdf_url.startswith("court/cnrorders/cghccisdb/orders/")

    j2 = sr.items[1]
    assert j2.case_number == "WP(C)/1234/2024"
    assert j2.source_id == "DLHC010012342024"
    assert j2.court_name == "Delhi High Court"
    assert j2.judgment_date == date(2024, 2, 15)
    assert j2.bench_type == "Division Bench"


def test_parse_search_response_empty():
    sr = parse_search_response(
        {"reportrow": {"aaData": [], "iTotalDisplayRecords": 0}},
        page=1,
        page_size=10,
    )
    assert sr.total_count == 0
    assert len(sr.items) == 0
    assert sr.has_next is False


def test_parse_search_response_missing_reportrow():
    sr = parse_search_response({}, page=1, page_size=10)
    assert sr.total_count == 0
    assert sr.items == []


def test_parse_search_response_pagination():
    payload = {
        "reportrow": {
            "aaData": [],
            "iTotalDisplayRecords": 100,
        },
    }
    sr_p1 = parse_search_response(payload, page=1, page_size=10)
    assert sr_p1.has_next is True

    sr_p10 = parse_search_response(payload, page=10, page_size=10)
    assert sr_p10.has_next is False  # 10 * 10 = 100, no more pages
