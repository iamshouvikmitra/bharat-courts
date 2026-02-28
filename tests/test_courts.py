"""Tests for court registry."""

from bharat_courts.courts import (
    SUPREME_COURT,
    get_court,
    get_court_by_name,
    list_all_courts,
    list_high_courts,
)
from bharat_courts.models import CourtType


def test_get_court_by_code():
    court = get_court("delhi")
    assert court is not None
    assert court.name == "Delhi High Court"
    assert court.state_code == "26"


def test_get_court_case_insensitive():
    assert get_court("Delhi") is not None
    assert get_court("DELHI") is not None


def test_get_court_not_found():
    assert get_court("nonexistent") is None


def test_get_court_by_name():
    court = get_court_by_name("Delhi High Court")
    assert court is not None
    assert court.code == "delhi"


def test_get_court_by_name_case_insensitive():
    assert get_court_by_name("delhi high court") is not None


def test_supreme_court():
    assert SUPREME_COURT.code == "sci"
    assert SUPREME_COURT.court_type == CourtType.SUPREME_COURT


def test_list_high_courts():
    hcs = list_high_courts()
    assert len(hcs) >= 25
    assert all(c.court_type == CourtType.HIGH_COURT for c in hcs)


def test_list_all_courts_includes_sc():
    all_courts = list_all_courts()
    codes = [c.code for c in all_courts]
    assert "sci" in codes
    assert "delhi" in codes


def test_bench_courts():
    court = get_court("bombay-nagpur")
    assert court is not None
    assert court.bench == "Nagpur"
    assert court.state_code == "1"  # Same as main Bombay HC
