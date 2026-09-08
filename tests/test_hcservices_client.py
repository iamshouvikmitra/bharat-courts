"""Tests for HC Services client using respx mocks."""

from pathlib import Path

import pytest
import respx
from httpx import Response

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.courts import get_court
from bharat_courts.hcservices import endpoints
from bharat_courts.hcservices.client import HCServicesClient
from bharat_courts.hcservices.endpoints import (
    CAPTCHA_IMAGE_URL,
    INDEX_QRY_URL,
    MAIN_PAGE_URL,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class AutoCaptchaSolver(CaptchaSolver):
    async def solve(self, image_bytes: bytes) -> str:
        return "test123"


@pytest.fixture
def fast_config():
    return BharatCourtsConfig(request_delay=0, timeout=5, max_retries=1)


@pytest.fixture
def captcha_solver():
    return AutoCaptchaSolver()


@pytest.mark.asyncio
async def test_case_status(fast_config, captcha_solver):
    fixture_html = (FIXTURES_DIR / "hcservices_case_status.html").read_text()
    delhi = get_court("delhi")

    with respx.mock:
        respx.get(MAIN_PAGE_URL).mock(return_value=Response(200, text="<html></html>"))
        respx.get(CAPTCHA_IMAGE_URL).mock(return_value=Response(200, content=b"fake_captcha_image"))
        respx.post(url__startswith=INDEX_QRY_URL).mock(
            return_value=Response(200, text=fixture_html)
        )

        async with HCServicesClient(config=fast_config, captcha_solver=captcha_solver) as client:
            results = await client.case_status(
                delhi, case_type="WP(C)", case_number="12345", year="2024"
            )

    assert len(results) == 2
    assert results[0].case_number == "WP(C)/12345/2024"
    assert results[0].court_name == "Delhi High Court"


# ------------------------------------------------------------------
# Empty CAPTCHA decodes never reach the wire (#5)
# ------------------------------------------------------------------


class FlakyCaptchaSolver(CaptchaSolver):
    """Returns unusable decodes for the first ``bad`` calls, then a good one.

    Mirrors OCRCaptchaSolver's contract: an unusable decode (wrong length,
    non-alphanumeric) comes back as an empty string.
    """

    def __init__(self, bad: int):
        self.bad = bad
        self.calls = 0

    async def solve(self, image_bytes: bytes) -> str:
        self.calls += 1
        return "" if self.calls <= self.bad else "test123"


@pytest.mark.asyncio
async def test_empty_captcha_skips_post_and_retries(fast_config):
    """An empty solver result must not be POSTed — the portal answers it with
    ERROR_VAL, which the retry loop doesn't catch, failing the whole call on
    one bad OCR read (#5). The attempt is skipped and a fresh session tried."""
    fixture_html = (FIXTURES_DIR / "hcservices_case_status.html").read_text()
    delhi = get_court("delhi")
    solver = FlakyCaptchaSolver(bad=2)

    with respx.mock:
        respx.get(MAIN_PAGE_URL).mock(return_value=Response(200, text="<html></html>"))
        respx.get(CAPTCHA_IMAGE_URL).mock(return_value=Response(200, content=b"fake_captcha_image"))
        search = respx.post(url__startswith=INDEX_QRY_URL).mock(
            return_value=Response(200, text=fixture_html)
        )

        async with HCServicesClient(config=fast_config, captcha_solver=solver) as client:
            results = await client.case_status(
                delhi, case_type="WP(C)", case_number="12345", year="2024"
            )

    assert len(results) == 2
    assert solver.calls == 3
    assert search.call_count == 1, "empty CAPTCHAs must never be sent to the portal"


@pytest.mark.asyncio
async def test_all_empty_captchas_raise_captcha_error(fast_config):
    from bharat_courts.hcservices.parser import CaptchaError

    delhi = get_court("delhi")
    solver = FlakyCaptchaSolver(bad=99)

    with respx.mock:
        respx.get(MAIN_PAGE_URL).mock(return_value=Response(200, text="<html></html>"))
        respx.get(CAPTCHA_IMAGE_URL).mock(return_value=Response(200, content=b"fake_captcha_image"))
        search = respx.post(url__startswith=INDEX_QRY_URL).mock(
            return_value=Response(200, text="should never be reached")
        )

        async with HCServicesClient(config=fast_config, captcha_solver=solver) as client:
            with pytest.raises(CaptchaError):
                await client.case_status(delhi, case_type="WP(C)", case_number="12345", year="2024")

    assert search.call_count == 0


# ------------------------------------------------------------------
# Advocate form builders
# ------------------------------------------------------------------


def test_advocate_form_by_name():
    form = endpoints.case_status_by_advocate_form(
        state_code="17", captcha="abc123", advocate_name="PRIYA SHARMA"
    )
    assert form["caseStatusSearchType"] == "CSAdvName"
    assert form["search_type"] == "1"
    assert form["advocate_name"] == "PRIYA SHARMA"
    assert "adv_bar_state" not in form


def test_advocate_form_by_bar_code():
    form = endpoints.case_status_by_advocate_form(
        state_code="17", captcha="abc123", bar_code="G/504/2011"
    )
    # NOT CSAdvNamebar -- sending that makes the server return ERROR_VAL
    assert form["caseStatusSearchType"] == "CSAdvName"
    assert form["search_type"] == "2"
    assert form["adv_bar_state"] == "G/504/2011"
    assert "advocate_name" not in form


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"advocate_name": "PRIYA SHARMA", "bar_code": "G/504/2011"},
    ],
)
def test_advocate_form_requires_exactly_one_selector(kwargs):
    with pytest.raises(ValueError):
        endpoints.case_status_by_advocate_form(state_code="17", captcha="abc123", **kwargs)


@pytest.mark.asyncio
async def test_case_status_by_advocate_is_a_view_over_advocate_search(fast_config, captcha_solver):
    """One request, two shapes — so the retry/annotation logic cannot drift."""
    fixture_json = (FIXTURES_DIR / "hcservices_advocate_search.json").read_text()
    gujarat = get_court("gujarat")

    with respx.mock:
        respx.get(MAIN_PAGE_URL).mock(return_value=Response(200, text="<html></html>"))
        respx.get(CAPTCHA_IMAGE_URL).mock(return_value=Response(200, content=b"fake_captcha_image"))
        respx.post(url__startswith=INDEX_QRY_URL).mock(
            return_value=Response(200, text=fixture_json)
        )

        async with HCServicesClient(config=fast_config, captcha_solver=captcha_solver) as client:
            full = await client.advocate_search(gujarat, bar_code="G/504/2011")
            cases = await client.case_status_by_advocate(gujarat, bar_code="G/504/2011")

    assert full.found is True
    assert full.name == "PRIYA SHARMA"
    # The thin view returns exactly the cases, court_name backfill included.
    assert [c.to_dict() for c in cases] == [c.to_dict() for c in full.cases]
    assert cases[0].court_name == gujarat.name


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"advocate_name": "PRIYA SHARMA", "bar_code": "G/504/2011"},
    ],
)
async def test_advocate_search_rejects_a_bad_query_before_the_captcha(
    kwargs, fast_config, captcha_solver
):
    """A manual solver blocks on a human, so validate before spending one."""
    gujarat = get_court("gujarat")

    with respx.mock:
        session = respx.get(MAIN_PAGE_URL).mock(return_value=Response(200, text="<html></html>"))
        captcha = respx.get(CAPTCHA_IMAGE_URL).mock(return_value=Response(200, content=b"img"))

        async with HCServicesClient(config=fast_config, captcha_solver=captcha_solver) as client:
            with pytest.raises(ValueError, match="exactly one"):
                await client.advocate_search(gujarat, **kwargs)

    assert session.call_count == 0
    assert captcha.call_count == 0


def test_advocate_cause_list_form():
    form = endpoints.advocate_cause_list_form(
        state_code="17", captcha="abc123", bar_code="G/504/2011", causelist_date="17-08-2026"
    )
    assert form["search_type"] == "3"
    assert form["f"] == "date_case_list"
    assert form["caselist_date_dmy"] == "17-08-2026"
    assert form["adv_bar_state"] == "G/504/2011"


# ------------------------------------------------------------------
# CNR lookup
# ------------------------------------------------------------------


def test_cnr_form():
    form = endpoints.case_status_by_cnr_form(cnr="GJHC240464312025", captcha="abc123")
    assert form["cino"] == "GJHC240464312025"
    assert form["action_code"] == "fetchStateDistCourtNew"
    # without this the server answers ERROR_caseStatusSearchTypeBlank
    assert form["caseStatusSearchType"] == "CNRNumber"
    assert form["appFlag"] == "web"


def test_cnr_form_normalises_case():
    form = endpoints.case_status_by_cnr_form(cnr=" gjhc240464312025 ", captcha="x")
    assert form["cino"] == "GJHC240464312025"


@pytest.mark.parametrize(
    "bad", ["", "TOO-SHORT", "GJHC24046431202", "GJHC2404643120255", "GJHC2404643120!5"]
)
async def test_cnr_lookup_rejects_malformed(bad):
    client = HCServicesClient()
    with pytest.raises(ValueError, match="16 alphanumeric"):
        await client.case_status_by_cnr(bad)
