"""Tests for HC Services parsers (JSON + HTML)."""

import json
from datetime import date
from unittest import mock

import pytest

from bharat_courts.hcservices import parser
from bharat_courts.hcservices.parser import (
    CaptchaError,
    ServerError,
    dedupe_by_cnr,
    is_captcha_rejection,
    parse_advocate_cause_list,
    parse_advocate_search,
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
    # case_type is now sourced from `type_name` (the real portal field)
    assert case1.case_type == "W.P.(C)"
    # registration_number is sourced from `case_no2`
    assert case1.registration_number == "3"
    # filing_number is the long `case_no` string
    assert case1.filing_number == "200300000032024"
    assert case1.petitioner == "ABC INDUSTRIES LTD"
    assert case1.respondent == "STATE POLLUTION CONTROL BOARD & ORS."
    # showRecords does not return status / registration_date
    assert case1.status == ""
    assert case1.registration_date is None

    case2 = results[1]
    assert case2.cnr_number == "DLHC010400092024"
    assert case2.case_type == "CRL.A."
    assert case2.registration_number == "9"
    assert case2.petitioner == "XYZ ENTERPRISES PVT LTD"
    assert case2.status == ""


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


def test_parse_orders_json():
    """Test parse_orders with JSON response containing orderurlpath."""
    import json

    records = [
        {
            "cino": "DLHC010582482024",
            "type_name": "WP(C)",
            "case_no2": "3",
            "case_year": "2024",
            "orderurlpath": "enc_path_abc123",
        },
        {
            "cino": "DLHC010400092024",
            "type_name": "CRL.A.",
            "case_no2": "567",
            "case_year": "2023",
            "orderurlpath": "enc_path_def456",
        },
    ]
    raw = json.dumps(
        {
            "con": [json.dumps(records)],
            "totRecords": "2",
            "Error": "",
        }
    )

    results = parse_orders(
        raw,
        base_url="https://hcservices.ecourts.gov.in/hcservices",
        bench_code="1",
        state_code="26",
    )
    assert len(results) == 2

    order1 = results[0]
    assert "display_pdf.php" in order1.pdf_url
    assert "filename=enc_path_abc123" in order1.pdf_url
    assert "cino=DLHC010582482024" in order1.pdf_url
    assert "cCode=1" in order1.pdf_url
    assert "state_code=26" in order1.pdf_url
    assert "caseno=WP(C)/3/2024" in order1.pdf_url

    order2 = results[1]
    assert "enc_path_def456" in order2.pdf_url
    assert "CRL.A./567/2023" in order2.pdf_url


def test_parse_orders_json_no_orderurlpath():
    """Records without orderurlpath are skipped."""
    import json

    records = [{"cino": "DLHC01", "case_no2": "1", "case_year": "2024"}]
    raw = json.dumps({"con": [json.dumps(records)], "totRecords": "1", "Error": ""})
    results = parse_orders(raw)
    assert results == []


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
    assert entry1.pdf_url.startswith(
        "https://hcservices.ecourts.gov.in/hcservices/cases/display_causelist_pdf.php?"
    )
    assert "/cases_qry/" not in entry1.pdf_url

    entry2 = results[1]
    assert entry2.serial_number == 2
    assert "SINGLE BENCH" in entry2.bench
    assert entry2.pdf_url != ""


def test_parse_cause_list_empty():
    assert parse_cause_list("<html></html>") == []


# ------------------------------------------------------------------
# Advocate search / advocate cause list
# ------------------------------------------------------------------


def test_parse_advocate_search_reuses_case_status(hcservices_advocate_search_json):
    """Advocate search returns the same envelope as any other case search."""
    results = parse_case_status(hcservices_advocate_search_json)
    assert len(results) == 2

    first = results[0]
    assert first.cnr_number == "GJHC240100012024"
    assert first.case_number == "1001/2024"
    assert first.case_type == "FA"
    assert first.petitioner == "ABC INDUSTRIES LTD"
    # showRecords never populates status, whatever the search mode
    assert first.status == ""


def test_parse_advocate_cause_list(hcservices_advocate_cause_list_json):
    entries = parse_advocate_cause_list(hcservices_advocate_cause_list_json)
    # four rows, because the portal repeats a case once per party
    assert len(entries) == 4

    first = entries[0]
    assert first.cnr_number == "GJHC240200012026"
    assert first.case_number == "2001/2026"
    assert first.case_type == "FA"
    assert first.petitioner == "ABC INDUSTRIES LTD"
    assert first.advocate_petitioner == "MS. PRIYA SHARMA(1234)"
    assert first.purpose == "181-FOR FINAL DISPOSAL"
    assert first.judge == "HONOURABLE MR.JUSTICE A B EXAMPLE"
    # date_next_list arrives as ISO, unlike most portal dates
    assert first.listing_date == date(2026, 8, 17)
    # court_no is an internal establishment code, not a display-board number
    assert first.court_number == "5377"
    # no serial number is returned by this endpoint
    assert first.item_number == ""
    assert first.serial_number == 0


def test_parse_advocate_cause_list_dedupe(hcservices_advocate_cause_list_json):
    """Rows 2 and 3 share a CNR; dedupe collapses them to one case."""
    entries = parse_advocate_cause_list(hcservices_advocate_cause_list_json)
    cases = dedupe_by_cnr(entries)
    assert len(cases) == 3
    assert [c.cnr_number for c in cases] == [
        "GJHC240200012026",
        "GJHC240200022025",
        "GJHC240200032024",
    ]
    # first row per CNR wins, so the first petitioner is kept
    assert cases[1].petitioner == "FIRST PETITIONER"


def test_advocate_cause_list_empty_envelope():
    entries = parse_advocate_cause_list('{"con": [], "totRecords": 0, "Error": ""}')
    assert entries == []


# Both dates ride on every row and mean different things: `date_next_list` is
# the listing being queried, `todays_date` is when the matter was last in
# court. Dropping the second loses the adjournment half of a diary entry.
def test_advocate_cause_list_carries_both_dates(hcservices_advocate_cause_list_json):
    from datetime import date

    entries = parse_advocate_cause_list(hcservices_advocate_cause_list_json)
    first = entries[0]
    assert first.listing_date == date(2026, 8, 17)
    assert first.business_date == date(2026, 8, 13)
    assert first.listing_date != first.business_date


# The envelope echoes back who the portal matched, and nothing else confirms
# a bar code: both portals take its state part as free text, so a wrong one
# is a search that finds nothing rather than an error.
def test_advocate_search_keeps_who_the_portal_matched(hcservices_advocate_search_json):
    result = parse_advocate_search(hcservices_advocate_search_json)
    assert result.found is True
    assert result.raw_name == "PRIYA SHARMA"
    assert result.total_records == 2
    assert len(result.cases) == 2


def test_a_bracketed_id_is_split_off_the_name():
    raw = json.dumps({"con": ["[]"], "totRecords": 0, "adv_name": "MR. HEMAL SHAH(6960)"})
    result = parse_advocate_search(raw)
    assert result.name == "MR. HEMAL SHAH"
    # The portal's internal advocate id — not a bar number, and not accepted
    # as one.
    assert result.code == "6960"


# An advocate with nothing pending is not a bad bar code, and the two need
# different words in front of a lawyer who has just signed up.
def test_found_with_no_cases_is_distinguishable_from_not_found():
    empty = parse_advocate_search(json.dumps({"con": ["[]"], "adv_name": ""}))
    assert empty.found is False

    quiet = parse_advocate_search(json.dumps({"con": ["[]"], "adv_name": "MR. SOMEONE(1)"}))
    assert quiet.found is True
    assert quiet.cases == []


# The envelope is where the echo lives, so this parser has to read it through
# the same helper as its siblings — a bare json.loads crashes on responses
# they absorb, and callers watching for CaptchaError/ServerError would get a
# raw JSONDecodeError instead.
@pytest.mark.parametrize(
    "label,raw",
    [
        ("session-expired HTML", "<html><table><tr><td>Session expired</td></tr></table></html>"),
        ("control char in the name", '{"con":["[]"],"totRecords":"0","adv_name":"MR. X\x01(1)"}'),
        ("BOM behind whitespace", '  ﻿{"con":["[]"],"totRecords":"0","adv_name":"MR. X(1)"}'),
    ],
)
def test_odd_responses_survive_like_they_do_in_case_status(label, raw):
    parse_case_status(raw)  # the sibling absorbs it; so must this one
    assert parse_advocate_search(raw).cases == []


def test_a_reworded_captcha_rejection_still_raises_captcha_error():
    # The portal's wording has drifted before, so the envelope matches any
    # `con` string mentioning a captcha rather than one literal phrase.
    with pytest.raises(CaptchaError):
        parse_advocate_search('{"con":"Wrong Captcha"}')


def test_a_server_error_raises_rather_than_reading_as_not_found():
    # ERROR_VAL must not arrive as found=False — it is ambiguous between a
    # bad bar code and a transient refusal, and only the caller can retry.
    with pytest.raises(ServerError):
        parse_advocate_search('{"con":[],"totRecords":"0","Error":"ERROR_VAL"}')


def test_the_response_is_decoded_once_not_twice(hcservices_advocate_search_json):
    # A live bar code answers with thousands of rows over several MB, so the
    # envelope must be parsed once and shared with the row mapping.
    with mock.patch.object(parser.json, "loads", side_effect=json.loads) as loads:
        parse_advocate_search(hcservices_advocate_search_json)
    envelope_and_inner = 2
    assert loads.call_count == envelope_and_inner


# The retry loop quick-checks the response instead of parsing several MB, so
# its verdict has to be the one _parse_json_envelope would reach. A rejection
# it misses is a CaptchaError raised on attempt 1 with four retries unused.
@pytest.mark.parametrize(
    "raw",
    [
        '{"con":"Invalid Captcha"}',
        '{"con": "Invalid Captcha"}',
        '{"con":"Wrong Captcha"}',
        '{"con":"invalid captcha, try again"}',
        '\ufeff{"con":"Invalid Captcha"}',
    ],
)
def test_captcha_rejections_are_recognised_without_a_full_parse(raw):
    assert is_captcha_rejection(raw) is True
    with pytest.raises(CaptchaError):
        parse_case_status(raw)


@pytest.mark.parametrize(
    "raw",
    [
        '{"con":["[{\\"cino\\": \\"GJHC240100012024\\"}]"],"totRecords":"1"}',
        '{"con":[],"totRecords":"0","Error":""}',
        # A captcha mentioned inside the rows is data, not a rejection.
        '{"con":["[{\\"pet_name\\": \\"CAPTCHA SOLUTIONS PVT LTD\\"}]"],"totRecords":"1"}',
        '{"con":[],"Error":"ERROR_VAL"}',
    ],
)
def test_successful_responses_are_not_read_as_captcha_rejections(raw):
    assert is_captcha_rejection(raw) is False
