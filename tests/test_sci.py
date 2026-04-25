"""Tests for SCIClient (www.sci.gov.in)."""

from datetime import date

import httpx
import pytest
import respx

from bharat_courts.models import JudgmentResult
from bharat_courts.sci.client import SCI_HOME_URL, SCIClient
from bharat_courts.sci.parser import (
    _build_pdf_url,
    _split_parties,
    parse_recent_judgments,
)


def test_build_pdf_url_swaps_path():
    view = (
        "https://www.sci.gov.in/view-pdf/?diary_no=94392025&type=j"
        "&order_date=2026-04-24&from=latest_judgements_order"
    )
    pdf = _build_pdf_url(view, "https://www.sci.gov.in")
    assert pdf == (
        "https://www.sci.gov.in/sci-get-pdf/?diary_no=94392025&type=j"
        "&order_date=2026-04-24&from=latest_judgements_order"
    )


def test_split_parties():
    pet, resp = _split_parties("X VS. Y")
    assert pet == "X"
    assert resp == "Y"

    pet, resp = _split_parties("STATE OF PUNJAB VS. SUKHWINDER SINGH @ GORA")
    assert pet == "STATE OF PUNJAB"
    assert resp == "SUKHWINDER SINGH @ GORA"

    pet, resp = _split_parties("just one")
    assert pet == "just one"
    assert resp == ""


def test_parse_recent_judgments_fixture(sci_home_html):
    items = parse_recent_judgments(sci_home_html)
    assert len(items) == 3

    j1 = items[0]
    assert isinstance(j1, JudgmentResult)
    assert j1.court_name == "Supreme Court of India"
    assert j1.case_number == "C.A. No. 6677/2026"
    assert j1.judgment_date == date(2026, 4, 24)
    assert j1.source_id == "94392025"
    assert j1.metadata["petitioner"] == "VINAY RAGHUNATH DESHMUKH"
    assert j1.metadata["respondent"] == "NATWARLAL SHAMJI GADA"
    assert j1.metadata["type"] == "j"
    assert j1.source_url.startswith("https://www.sci.gov.in/view-pdf/?diary_no=94392025")
    assert j1.pdf_url.startswith("https://www.sci.gov.in/sci-get-pdf/?diary_no=94392025")

    j3 = items[2]
    assert j3.metadata["petitioner"] == "STATE OF PUNJAB"
    assert j3.metadata["respondent"] == "SUKHWINDER SINGH @ GORA"
    assert j3.case_number == "Crl.A. No. 2143/2026"


def test_parse_recent_judgments_empty():
    items = parse_recent_judgments("<html><body></body></html>")
    assert items == []


@respx.mock
async def test_list_recent_judgments(sci_home_html):
    respx.get(SCI_HOME_URL).mock(return_value=httpx.Response(200, text=sci_home_html))

    async with SCIClient() as c:
        items = await c.list_recent_judgments()

    assert len(items) == 3
    assert items[0].source_id == "94392025"


@respx.mock
async def test_list_recent_judgments_limit(sci_home_html):
    respx.get(SCI_HOME_URL).mock(return_value=httpx.Response(200, text=sci_home_html))

    async with SCIClient() as c:
        items = await c.list_recent_judgments(limit=2)

    assert len(items) == 2


@respx.mock
async def test_download_pdf_success(sci_home_html):
    pdf = b"%PDF-1.7\n" + b"x" * 1000

    respx.get(SCI_HOME_URL).mock(return_value=httpx.Response(200, text=sci_home_html))
    respx.get(url__startswith="https://www.sci.gov.in/sci-get-pdf/").mock(
        return_value=httpx.Response(200, content=pdf)
    )

    async with SCIClient() as c:
        items = await c.list_recent_judgments()
        await c.download_pdf(items[0])

    assert items[0].pdf_bytes == pdf


@respx.mock
async def test_download_pdf_rejects_non_pdf(sci_home_html):
    respx.get(SCI_HOME_URL).mock(return_value=httpx.Response(200, text=sci_home_html))
    respx.get(url__startswith="https://www.sci.gov.in/sci-get-pdf/").mock(
        return_value=httpx.Response(200, content=b"<html>error</html>")
    )

    async with SCIClient() as c:
        items = await c.list_recent_judgments()
        with pytest.raises(RuntimeError, match="not return a valid PDF"):
            await c.download_pdf(items[0])


async def test_search_by_year_raises():
    async with SCIClient() as c:
        with pytest.raises(NotImplementedError, match="not supported"):
            await c.search_by_year(2024)


async def test_search_by_party_raises():
    async with SCIClient() as c:
        with pytest.raises(NotImplementedError, match="not supported"):
            await c.search_by_party("Union of India")
