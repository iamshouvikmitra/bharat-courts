"""Tests for HC Services parsers (JSON + HTML)."""

from datetime import date

import pytest

from bharat_courts.hcservices.parser import (
    CaptchaError,
    parse_case_status,
    parse_cause_list,
    parse_orders,
)

# ------------------------------------------------------------------
# JSON response tests (real format from showRecords)
# ------------------------------------------------------------------


def test_parse_case_status_json(hcservices_case_status_json):
    results = parse_case_status(hcservices_case_status_json)
    assert len(results) == 2

    case1 = results[0]
    assert case1.cnr_number == "DLHC010582482024"
    assert case1.case_number == "3/2024"
    assert case1.case_type == "3"
    assert case1.petitioner == "ABC INDUSTRIES LTD"
    assert case1.respondent == "STATE POLLUTION CONTROL BOARD & ORS."

    case2 = results[1]
    assert case2.cnr_number == "DLHC010400092024"
    assert case2.petitioner == "XYZ ENTERPRISES PVT LTD"
    assert case2.status == "Disposed"


def test_parse_case_status_json_captcha_error():
    raw = '{"con":"Invalid Captcha"}'
    with pytest.raises(CaptchaError):
        parse_case_status(raw)


def test_parse_case_status_json_empty():
    raw = '{"con":[],"totRecords":"0","Error":""}'
    results = parse_case_status(raw)
    assert results == []


# ------------------------------------------------------------------
# HTML response tests (legacy fallback)
# ------------------------------------------------------------------


def test_parse_case_status(hcservices_case_status_html):
    results = parse_case_status(hcservices_case_status_html)
    assert len(results) == 2

    case1 = results[0]
    assert case1.case_number == "WP(C)/12345/2024"
    assert case1.petitioner == "ABC Industries Ltd"
    assert case1.respondent == "Union of India"
    assert case1.status == "Pending"
    assert case1.registration_date == date(2024, 1, 20)

    case2 = results[1]
    assert case2.case_number == "CRL.A./567/2023"
    assert case2.petitioner == "State of Delhi"
    assert case2.respondent == "XYZ Enterprises"
    assert case2.status == "Disposed"


def test_parse_case_status_empty():
    assert parse_case_status("<html><body>No results</body></html>") == []


def test_parse_orders(hcservices_orders_html):
    results = parse_orders(hcservices_orders_html, base_url="https://hcservices.ecourts.gov.in")
    assert len(results) == 2

    order1 = results[0]
    assert order1.order_date == date(2024, 2, 15)
    assert order1.order_type == "Judgment"
    assert "Division Bench" in order1.judge
    assert order1.pdf_url.endswith("order_123.pdf")

    order2 = results[1]
    assert order2.order_type == "Interim Order"


def test_parse_orders_empty():
    assert parse_orders("<html></html>") == []


def test_parse_cause_list(hcservices_cause_list_html):
    results = parse_cause_list(
        hcservices_cause_list_html, base_url="https://hcservices.ecourts.gov.in/hcservices"
    )
    assert len(results) == 2

    entry1 = results[0]
    assert entry1.serial_number == 1
    assert "DIVISION BENCH" in entry1.bench
    assert entry1.cause_list_type == "COMPLETE CAUSE LIST"
    assert "display_causelist_pdf.php" in entry1.pdf_url

    entry2 = results[1]
    assert entry2.serial_number == 2
    assert "SINGLE BENCH" in entry2.bench
    assert entry2.pdf_url != ""


def test_parse_cause_list_empty():
    assert parse_cause_list("<html></html>") == []
