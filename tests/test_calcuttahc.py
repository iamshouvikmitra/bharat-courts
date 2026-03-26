"""Tests for Calcutta High Court client and parser."""

import json

import pytest

from bharat_courts.calcuttahc import endpoints
from bharat_courts.calcuttahc.parser import parse_search_response, to_case_orders

# --- Sample response from the portal (verified via live testing) ---

SAMPLE_RESPONSE = json.dumps({
    "cino": "WBCHCA0239512024",
    "case_type_name": "WPA",
    "reg_no": "12886",
    "year": "2024",
    "side": "Calcutta High Court - Appellate Side",
    "full_Case_num": "WPA/12886/2024",
    "cause_title": (
        "<b>SOURAV ROY BHOWMICK<br>-vs-<br>"
        "THE UNION OF INDIA AND ORS."
    ),
    "list": (
        '<tr><td>1</td>'
        "<td>10-05-2024</td>"
        "<td>HON'BLE JUSTICE SABYASACHI BHATTACHARYYA</td>"
        "<td>Order<br><small>Neutral Citation:</small><br>2024:CHC-AS:1277</td>"
        '<td><button class="btn btn-sm btn-primary showorder" '
        'onclick=\'show_order("1~201200128862024~1~WBCHCA0239512024~2024")\'>'
        "View Order</button></td></tr>"
    ),
})


# --- Endpoint tests ---


def test_search_form():
    form = endpoints.search_form(
        token="abc123",
        establishment="WBCHCA",
        case_type="12",
        case_number="12886",
        year="2024",
        captcha="xyz",
    )
    assert form["_token"] == "abc123"
    assert form["order_establishment"] == "WBCHCA"
    assert form["order_casetype"] == "12"
    assert form["order_reg_no"] == "12886"
    assert form["order_year"] == "2024"
    assert form["captcha"] == "xyz"


def test_show_pdf_form():
    form = endpoints.show_pdf_form(
        token="abc123",
        order_data="1~201200128862024~1~WBCHCA0239512024~2024",
    )
    assert form["_token"] == "abc123"
    assert form["order_data"] == "1~201200128862024~1~WBCHCA0239512024~2024"


def test_establishments():
    assert endpoints.ESTABLISHMENTS["appellate"] == "WBCHCA"
    assert endpoints.ESTABLISHMENTS["original"] == "WBCHCO"
    assert "jalpaiguri" in endpoints.ESTABLISHMENTS
    assert "portblair" in endpoints.ESTABLISHMENTS


# --- Parser tests ---


def test_parse_search_response():
    result = parse_search_response(SAMPLE_RESPONSE)
    assert result["cino"] == "WBCHCA0239512024"
    assert result["full_case_num"] == "WPA/12886/2024"
    assert "SOURAV ROY BHOWMICK" in result["cause_title"]
    assert "UNION OF INDIA" in result["cause_title"]
    assert len(result["orders"]) == 1

    order = result["orders"][0]
    assert order["order_num"] == "1"
    assert order["order_date"] == "10-05-2024"
    assert "SABYASACHI BHATTACHARYYA" in order["judge"]
    assert order["order_type"] == "Order"
    assert order["neutral_citation"] == "2024:CHC-AS:1277"
    assert order["order_data"] == "1~201200128862024~1~WBCHCA0239512024~2024"


def test_parse_search_response_double_encoded():
    """The portal sometimes returns double-encoded JSON."""
    double_encoded = json.dumps(SAMPLE_RESPONSE)
    result = parse_search_response(double_encoded)
    assert result["cino"] == "WBCHCA0239512024"
    assert len(result["orders"]) == 1


def test_parse_search_response_empty_list():
    data = json.dumps({"cino": "X", "full_Case_num": "Y", "cause_title": "", "list": ""})
    result = parse_search_response(data)
    assert result["orders"] == []


def test_to_case_orders():
    parsed = parse_search_response(SAMPLE_RESPONSE)
    pdf_urls = {
        "1~201200128862024~1~WBCHCA0239512024~2024": "https://example.com/order.pdf",
    }
    orders = to_case_orders(parsed, pdf_urls)
    assert len(orders) == 1

    o = orders[0]
    assert str(o.order_date) == "2024-05-10"
    assert o.order_type == "Order"
    assert "SABYASACHI BHATTACHARYYA" in o.judge
    assert o.neutral_citation == "2024:CHC-AS:1277"
    assert o.pdf_url == "https://example.com/order.pdf"


def test_to_case_orders_no_pdf_urls():
    parsed = parse_search_response(SAMPLE_RESPONSE)
    orders = to_case_orders(parsed)
    assert len(orders) == 1
    assert orders[0].pdf_url == ""
    assert orders[0].neutral_citation == "2024:CHC-AS:1277"


# --- Client tests (mocked) ---


@pytest.mark.asyncio
async def test_client_init():
    """CalcuttaHCClient can be instantiated."""
    from bharat_courts.calcuttahc.client import CalcuttaHCClient

    client = CalcuttaHCClient()
    assert client._csrf_token == ""
    assert client._owns_http is True
