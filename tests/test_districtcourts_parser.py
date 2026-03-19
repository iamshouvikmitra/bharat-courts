"""Tests for District Courts parsers."""

from datetime import date
from pathlib import Path

import pytest

from bharat_courts.districtcourts.parser import (
    CaptchaError,
    ServerError,
    parse_ajax_response,
    parse_case_status_html,
    parse_cause_list_html,
    parse_complex_value,
    parse_court_orders_html,
    parse_option_tags,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ------------------------------------------------------------------
# AJAX response envelope
# ------------------------------------------------------------------


def test_parse_ajax_response_success():
    raw = '{"status": 1, "app_token": "abc123", "party_data": "<table></table>"}'
    result = parse_ajax_response(raw)
    assert result["status"] == 1
    assert result["app_token"] == "abc123"
    assert result["party_data"] == "<table></table>"


def test_parse_ajax_response_captcha_error():
    raw = '{"status": 0, "app_token": "xyz", "div_captcha": "<img...>"}'
    with pytest.raises(CaptchaError):
        parse_ajax_response(raw)


def test_parse_ajax_response_server_error():
    raw = '{"status": 1, "errormsg": "Session expired"}'
    with pytest.raises(ServerError):
        parse_ajax_response(raw)


def test_parse_ajax_response_with_bom():
    raw = '\ufeff{"status": 1, "app_token": "tok1", "data": "ok"}'
    result = parse_ajax_response(raw)
    assert result["app_token"] == "tok1"


def test_parse_ajax_response_non_json():
    raw = "<html>error page</html>"
    result = parse_ajax_response(raw)
    assert result["status"] == 0


# ------------------------------------------------------------------
# Option tag parsing
# ------------------------------------------------------------------


def test_parse_option_tags():
    html = (FIXTURES_DIR / "districtcourts_districts.html").read_text()
    result = parse_option_tags(html)
    assert "1" in result
    assert result["1"] == "Patna"
    assert "24" in result
    assert result["24"] == "Araria"
    # Placeholder should be filtered out
    assert "" not in result
    assert len(result) == 5


def test_parse_option_tags_empty():
    result = parse_option_tags('<option value="0">Select district</option>')
    assert result == {}


def test_parse_option_tags_complexes():
    html = (FIXTURES_DIR / "districtcourts_complexes.html").read_text()
    result = parse_option_tags(html)
    assert len(result) == 3
    assert "1080010@2,3,4@Y" in result
    assert result["1080010@2,3,4@Y"] == "Civil Court, Patna Sadar"


# ------------------------------------------------------------------
# Complex value parsing
# ------------------------------------------------------------------


def test_parse_complex_value_with_flag():
    code, ests, needs_est = parse_complex_value("1080010@2,3,4@Y")
    assert code == "1080010"
    assert ests == ["2", "3", "4"]
    assert needs_est is True


def test_parse_complex_value_no_flag():
    code, ests, needs_est = parse_complex_value("1080010@5,6@N")
    assert code == "1080010"
    assert ests == ["5", "6"]
    assert needs_est is False


def test_parse_complex_value_simple():
    code, ests, needs_est = parse_complex_value("12345")
    assert code == "12345"
    assert ests == []
    assert needs_est is False


# ------------------------------------------------------------------
# Case status HTML parsing
# ------------------------------------------------------------------


def test_parse_case_status_html():
    html = (FIXTURES_DIR / "districtcourts_case_status.html").read_text()
    results = parse_case_status_html(html)

    assert len(results) == 3

    case1 = results[0]
    assert case1.case_number == "CS/123/2024"
    assert case1.case_type == "CS"
    assert case1.petitioner == "Ram Kumar Singh"
    assert case1.respondent == "State of Bihar"
    assert case1.cnr_number == "BHAR010001232024"
    assert case1.registration_date == date(2024, 1, 15)
    assert case1.status == "Pending"
    assert case1.next_hearing_date == date(2026, 4, 25)

    case2 = results[1]
    assert case2.case_number == "CRA/456/2023"
    assert case2.petitioner == "Sita Devi"
    assert case2.respondent == "Manoj Kumar"
    assert case2.status == "Disposed"
    assert case2.next_hearing_date is None

    case3 = results[2]
    assert case3.case_number == "MJC/789/2024"
    assert case3.petitioner == "ABC Enterprises Pvt Ltd"
    # No CNR in onclick for case3
    assert case3.cnr_number == ""


def test_parse_case_status_html_live_format():
    """Test with the real portal format (4 columns, <br>Vs</br> separator)."""
    html = (FIXTURES_DIR / "districtcourts_case_status_live.html").read_text()
    results = parse_case_status_html(html)

    assert len(results) == 3

    case1 = results[0]
    assert case1.case_number == "Title Appeal/47/2024"
    assert case1.case_type == "Title Appeal"
    assert case1.petitioner == "Bankim Chand and 15 others"
    assert case1.respondent == "Surendra Prasad Sah and 32 others"
    assert case1.cnr_number == "BRPA010216322024"

    case2 = results[1]
    assert case2.petitioner == "Indu Devi and another"
    assert case2.respondent == "Arun Kumar Sharma and 2 others"
    assert case2.cnr_number == "BRPA010207032024"

    # Third row uses <strong> tags (the other format)
    case3 = results[2]
    assert case3.petitioner == "Rajesh Verma"
    assert case3.respondent == "Municipal Corporation"
    assert case3.cnr_number == "BRPA010099992024"


def test_parse_case_status_html_empty():
    result = parse_case_status_html("<div>No records found</div>")
    assert result == []


def test_parse_case_status_html_empty_table():
    html = "<table><thead><tr><th>Sr</th></tr></thead><tbody></tbody></table>"
    result = parse_case_status_html(html)
    assert result == []


# ------------------------------------------------------------------
# Court orders HTML parsing
# ------------------------------------------------------------------


def test_parse_court_orders_html():
    html = (FIXTURES_DIR / "districtcourts_court_orders.html").read_text()
    results = parse_court_orders_html(
        html, base_url="https://services.ecourts.gov.in/ecourtindia_v6"
    )

    assert len(results) == 2

    order1 = results[0]
    assert order1.order_date == date(2024, 3, 15)
    assert order1.order_type == "Interim Order"
    assert order1.judge == "Sri Amit Kumar, ADJ-1"
    assert "display_pdf.php" in order1.pdf_url

    order2 = results[1]
    assert order2.order_date == date(2024, 1, 10)
    assert order2.order_type == "Order"
    assert order2.pdf_url.startswith("https://")


def test_parse_court_orders_html_empty():
    result = parse_court_orders_html("<p>No orders</p>")
    assert result == []


# ------------------------------------------------------------------
# Cause list HTML parsing
# ------------------------------------------------------------------


def test_parse_cause_list_html():
    html = (FIXTURES_DIR / "districtcourts_cause_list.html").read_text()
    results = parse_cause_list_html(html)

    assert len(results) == 2

    entry1 = results[0]
    assert entry1.serial_number == 1
    assert entry1.case_number == "CS/100/2024"
    assert entry1.case_type == "CS"
    assert entry1.petitioner == "Rajesh Verma"
    assert entry1.respondent == "Municipal Corporation"
    assert entry1.advocate_petitioner == "Adv. A.K. Mishra"
    assert entry1.court_number == "Court No. 3"
    assert entry1.judge == "Sri R.K. Jha, ADJ-3"

    entry2 = results[1]
    assert entry2.case_number == "CRA/200/2023"
    assert entry2.petitioner == "State of Bihar"


def test_parse_cause_list_html_empty():
    result = parse_cause_list_html("<div>No cause list</div>")
    assert result == []
