"""Tests for data models."""

from datetime import date

from bharat_courts.models import (
    CaseInfo,
    CaseOrder,
    CauseListEntry,
    Court,
    CourtType,
    JudgmentResult,
    SearchResult,
)


def test_court_slug():
    court = Court(
        name="Delhi High Court", code="delhi", state_code="6", court_type=CourtType.HIGH_COURT
    )
    assert court.slug == "delhi"


def test_court_frozen():
    court = Court(name="Test", code="test", state_code="0", court_type=CourtType.HIGH_COURT)
    try:
        court.name = "Changed"
        assert False, "Should raise FrozenInstanceError"
    except AttributeError:
        pass


def test_case_info_defaults():
    case = CaseInfo(case_number="WP(C)/123/2024", case_type="WP(C)")
    assert case.status == ""
    assert case.judges == []
    assert case.petitioner == ""


def test_case_order():
    order = CaseOrder(order_date=date(2024, 2, 15), order_type="Judgment")
    assert order.pdf_bytes is None
    assert order.order_text == ""


def test_judgment_result():
    j = JudgmentResult(
        title="ABC Industries v Union of India",
        court_name="Delhi HC",
        judges=["Justice A", "Justice B"],
    )
    assert len(j.judges) == 2
    assert j.pdf_bytes is None


def test_cause_list_entry():
    entry = CauseListEntry(serial_number=1, case_number="WP(C)/123/2024")
    assert entry.case_type == ""
    assert entry.listing_date is None


def test_search_result_total_pages():
    r = SearchResult(total_count=45, page_size=10)
    assert r.total_pages == 5

    r2 = SearchResult(total_count=50, page_size=10)
    assert r2.total_pages == 5

    r3 = SearchResult(total_count=0, page_size=10)
    assert r3.total_pages == 0

    r4 = SearchResult(total_count=10, page_size=0)
    assert r4.total_pages == 0
