"""Tests for HC Services client using respx mocks."""

from pathlib import Path

import pytest
import respx
from httpx import Response

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.courts import get_court
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
