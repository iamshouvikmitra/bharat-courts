"""Tests for District Courts client using respx mocks."""

import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.districtcourts.client import DistrictCourtClient
from bharat_courts.districtcourts.endpoints import BASE_URL, CAPTCHA_IMAGE_URL

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


def _ajax_response(*, status=1, app_token="tok_new", **kwargs):
    """Build a mock AJAX response."""
    data = {"status": status, "app_token": app_token, **kwargs}
    return Response(200, text=json.dumps(data))


def _mock_session_init():
    """Set up mocks for session initialization (GET base + getCaptcha)."""
    respx.get(url__startswith=BASE_URL).mock(return_value=Response(200, text="<html></html>"))
    respx.get(url__startswith=CAPTCHA_IMAGE_URL).mock(
        return_value=Response(200, content=b"fake_captcha_image")
    )


@pytest.mark.asyncio
async def test_list_districts(fast_config, captcha_solver):
    districts_html = (FIXTURES_DIR / "districtcourts_districts.html").read_text()

    with respx.mock:
        _mock_session_init()
        # getCaptcha (init)
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        # fillDistrict
        respx.post(url__regex=r".*fillDistrict").mock(
            return_value=_ajax_response(dist_list=districts_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            districts = await client.list_districts("8")

    assert len(districts) == 5
    assert districts["1"] == "Patna"
    assert districts["24"] == "Araria"


@pytest.mark.asyncio
async def test_list_complexes(fast_config, captcha_solver):
    districts_html = (FIXTURES_DIR / "districtcourts_districts.html").read_text()
    complexes_html = (FIXTURES_DIR / "districtcourts_complexes.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*fillDistrict").mock(
            return_value=_ajax_response(dist_list=districts_html)
        )
        respx.post(url__regex=r".*fillcomplex").mock(
            return_value=_ajax_response(complex_list=complexes_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            complexes = await client.list_complexes("8", "1")

    assert len(complexes) == 3
    assert "1080010@2,3,4@Y" in complexes
    assert complexes["1080010@2,3,4@Y"] == "Civil Court, Patna Sadar"


@pytest.mark.asyncio
async def test_case_status(fast_config, captcha_solver):
    case_html = (FIXTURES_DIR / "districtcourts_case_status.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*submitCaseNo").mock(
            return_value=_ajax_response(case_data=case_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            results = await client.case_status(
                state_code="8",
                dist_code="1",
                court_complex_code="1080010",
                est_code="2",
                case_type="1",
                case_number="123",
                year="2024",
            )

    assert len(results) == 3
    assert results[0].case_number == "CS/123/2024"
    assert results[0].petitioner == "Ram Kumar Singh"
    assert results[0].cnr_number == "BHAR010001232024"


@pytest.mark.asyncio
async def test_case_status_by_party(fast_config, captcha_solver):
    case_html = (FIXTURES_DIR / "districtcourts_case_status.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*submitPartyName").mock(
            return_value=_ajax_response(party_data=case_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            results = await client.case_status_by_party(
                state_code="8",
                dist_code="1",
                court_complex_code="1080010",
                party_name="Ram Kumar",
                year="2024",
            )

    assert len(results) == 3
    assert results[0].petitioner == "Ram Kumar Singh"


@pytest.mark.asyncio
async def test_court_orders(fast_config, captcha_solver):
    orders_html = (FIXTURES_DIR / "districtcourts_court_orders.html").read_text()

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*courtorder/submitCaseNo").mock(
            return_value=_ajax_response(order_data=orders_html)
        )

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            results = await client.court_orders(
                state_code="8",
                dist_code="1",
                court_complex_code="1080010",
                case_type="1",
                case_number="123",
                year="2024",
            )

    assert len(results) == 2
    assert results[0].order_type == "Interim Order"
    assert "display_pdf.php" in results[0].pdf_url


@pytest.mark.asyncio
async def test_captcha_retry(fast_config, captcha_solver):
    """Test that CAPTCHA retry creates fresh sessions."""
    case_html = (FIXTURES_DIR / "districtcourts_case_status.html").read_text()
    call_count = {"submitCaseNo": 0}

    def submit_side_effect(request):
        call_count["submitCaseNo"] += 1
        if call_count["submitCaseNo"] == 1:
            # First attempt: CAPTCHA failure
            return Response(
                200, text=json.dumps({"status": 0, "app_token": "tok2", "div_captcha": "<img>"})
            )
        # Second attempt: success
        return Response(
            200, text=json.dumps({"status": 1, "app_token": "tok3", "case_data": case_html})
        )

    fast_config_retry = BharatCourtsConfig(request_delay=0, timeout=5, max_retries=1)

    with respx.mock:
        _mock_session_init()
        respx.post(url__regex=r".*getCaptcha").mock(
            return_value=_ajax_response(div_captcha="<img>")
        )
        respx.post(url__regex=r".*set_data").mock(return_value=_ajax_response())
        respx.post(url__regex=r".*submitCaseNo").mock(side_effect=submit_side_effect)

        async with DistrictCourtClient(
            config=fast_config_retry, captcha_solver=captcha_solver
        ) as client:
            results = await client.case_status(
                state_code="8",
                dist_code="1",
                court_complex_code="1080010",
                case_type="1",
                case_number="123",
                year="2024",
                # Allow enough retries
            )

    assert len(results) == 3
    assert call_count["submitCaseNo"] == 2


@pytest.mark.asyncio
async def test_app_token_rotation(fast_config, captcha_solver):
    """Verify that app_token from responses is used in subsequent requests."""
    captured_tokens = []

    def capture_token(request):
        body = request.content.decode()
        for part in body.split("&"):
            if part.startswith("app_token="):
                captured_tokens.append(part.split("=", 1)[1])
        return Response(
            200,
            text=json.dumps(
                {
                    "status": 1,
                    "app_token": f"tok_{len(captured_tokens)}",
                    "dist_list": '<option value="1">Patna</option>',
                }
            ),
        )

    with respx.mock:
        _mock_session_init()
        respx.post(url__startswith=BASE_URL).mock(side_effect=capture_token)

        async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
            await client.list_districts("8")

    # First call (getCaptcha) should have empty token, subsequent should have rotated tokens
    assert captured_tokens[0] == ""  # Initial empty token
    # After getCaptcha returns tok_1, next call should use it
    assert captured_tokens[1] == "tok_1"


@pytest.mark.asyncio
async def test_list_states(fast_config, captcha_solver):
    """list_states returns the static state code mapping."""
    async with DistrictCourtClient(config=fast_config, captcha_solver=captcha_solver) as client:
        states = await client.list_states()

    assert "8" in states
    assert states["8"] == "Bihar"
    assert "7" in states
    assert states["7"] == "Delhi"
    assert len(states) == 36
