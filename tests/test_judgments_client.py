"""Tests for the Judgment Search portal client."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.hcservices.parser import CaptchaError
from bharat_courts.judgments import endpoints
from bharat_courts.judgments.client import JudgmentSearchClient


class _FixedCaptchaSolver(CaptchaSolver):
    """Test solver that always returns the same string."""

    async def solve(self, image_bytes: bytes) -> str:
        return "abc123"


class _EmptyCaptchaSolver(CaptchaSolver):
    """Test solver that always returns empty (simulating an unsolvable captcha)."""

    async def solve(self, image_bytes: bytes) -> str:
        return ""


_SAMPLE_RESPONSE = json.loads(
    (Path(__file__).parent / "fixtures" / "judgments_search_response.json").read_text()
)


def _setup_auth_routes(mock: respx.MockRouter, *, captcha_status: str = "Y") -> None:
    """Wire the GET / + GET captcha + POST checkCaptcha routes."""
    mock.get(endpoints.MAIN_PAGE_URL).mock(return_value=httpx.Response(200, text="<html></html>"))
    mock.get(endpoints.CAPTCHA_IMAGE_URL).mock(
        return_value=httpx.Response(200, content=b"fake-captcha-png")
    )
    mock.post(endpoints.CHECK_CAPTCHA_URL).mock(
        return_value=httpx.Response(
            200,
            json={"captcha_status": captcha_status, "app_token": "tok-1"},
        )
    )


# -- token helpers ----------------------------------------------------------


def test_update_token_from_response():
    client = JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver())
    assert client._app_token == ""
    client._update_token_from_response({"app_token": "tok_abc"})
    assert client._app_token == "tok_abc"


def test_update_token_ignores_empty():
    client = JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver())
    client._app_token = "existing"
    client._update_token_from_response({"app_token": ""})
    assert client._app_token == "existing"


# -- ##### envelope ---------------------------------------------------------


@respx.mock
async def test_validate_captcha_recovers_token_from_envelope():
    """When the portal returns a length-error '<msg>####<token>' body, we
    should still capture the rotated token before returning False."""
    body = (
        "Captcha should be less than 6 characters..!<br/>#####"
        "f4f49f32237f398d6faa1f442429ee5d751fa544e67d68fb98c1a247e9aa225e"
    )
    respx.get(endpoints.MAIN_PAGE_URL).mock(return_value=httpx.Response(200, text=""))
    respx.get(endpoints.CAPTCHA_IMAGE_URL).mock(return_value=httpx.Response(200, content=b"png"))
    respx.post(endpoints.CHECK_CAPTCHA_URL).mock(return_value=httpx.Response(200, text=body))

    client = JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver())
    async with client:
        ok = await client._validate_captcha("badcap", "test")

    assert ok is False
    assert client._app_token == ("f4f49f32237f398d6faa1f442429ee5d751fa544e67d68fb98c1a247e9aa225e")


# -- search -----------------------------------------------------------------


@respx.mock
async def test_search_parses_real_response_shape():
    _setup_auth_routes(respx)
    respx.post(endpoints.SEARCH_RESULTS_URL).mock(
        return_value=httpx.Response(200, json=_SAMPLE_RESPONSE)
    )

    async with JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver()) as client:
        sr = await client.search("section 498A", page=1, page_size=10)

    assert sr.total_count == 54122
    assert len(sr.items) == 2
    assert sr.items[0].case_number == "CRMP/1144/2026"
    assert sr.items[0].source_id == "CGHC010160032026"
    # token rotated from the search response
    assert client._app_token == _SAMPLE_RESPONSE["app_token"]


@respx.mock
async def test_search_raises_captcha_error_when_solver_gives_up():
    """Empty SearchResult must NOT be returned silently when CAPTCHA can't be solved.
    The previous behaviour (return SearchResult()) made 'no results' indistinguishable
    from 'we gave up'."""
    respx.get(endpoints.MAIN_PAGE_URL).mock(return_value=httpx.Response(200, text=""))
    respx.get(endpoints.CAPTCHA_IMAGE_URL).mock(return_value=httpx.Response(200, content=b"png"))

    async with JudgmentSearchClient(captcha_solver=_EmptyCaptchaSolver()) as client:
        with pytest.raises(CaptchaError):
            await client.search("anything", max_captcha_attempts=2)


@respx.mock
async def test_search_pagination_uses_idisplaystart():  # noqa: N802
    """Page 3 with size 10 should produce iDisplayStart=20."""
    _setup_auth_routes(respx)
    captured: dict = {}

    def search_route(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs

        captured["body"] = parse_qs(request.content.decode())
        return httpx.Response(
            200,
            json={
                "reportrow": {"aaData": [], "iTotalDisplayRecords": 0},
                "app_token": "tok-2",
            },
        )

    respx.post(endpoints.SEARCH_RESULTS_URL).mock(side_effect=search_route)

    async with JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver()) as client:
        await client.search("x", page=3, page_size=10)

    assert captured["body"]["iDisplayStart"] == ["20"]
    assert captured["body"]["iDisplayLength"] == ["10"]
    assert captured["body"]["search_txt1"] == ["x"]
