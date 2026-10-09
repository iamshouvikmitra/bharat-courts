"""Tests for the Judgment Search portal client."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.hcservices.parser import CaptchaError
from bharat_courts.judgments import endpoints
from bharat_courts.judgments.client import JudgmentSearchClient, normalize_act_text


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


# -- act filter -------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Negotiable Instruments Act, 1881", "Negotiable Instruments Act"),
        ("  NEGOTIABLE  ", "NEGOTIABLE"),
        ("Arbitration & Conciliation Act, 1996", "Arbitration Conciliation Act"),
    ],
)
def test_normalize_act_text(raw, expected):
    assert normalize_act_text(raw) == expected


def test_normalize_act_text_rejects_no_letters():
    with pytest.raises(ValueError):
        normalize_act_text("1881, 138")


@respx.mock
async def test_search_by_act_alone_sends_act_fields():
    """An act search needs no keywords; the act is normalised before sending."""
    _setup_auth_routes(respx)
    captured: dict = {}

    def search_route(request: httpx.Request) -> httpx.Response:
        from urllib.parse import parse_qs

        captured["body"] = parse_qs(request.content.decode(), keep_blank_values=True)
        return httpx.Response(200, json=_SAMPLE_RESPONSE)

    respx.post(endpoints.SEARCH_RESULTS_URL).mock(side_effect=search_route)

    async with JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver()) as client:
        sr = await client.search(act="Negotiable Instruments Act, 1881", section="138")

    assert sr.total_count == 54122
    assert captured["body"]["search_txt1"] == [""]
    assert captured["body"]["act_txt"] == ["Negotiable Instruments Act"]
    assert captured["body"]["section_txt"] == ["138"]


async def test_search_without_text_or_act_raises_before_captcha():
    async with JudgmentSearchClient(captcha_solver=_EmptyCaptchaSolver()) as client:
        with pytest.raises(ValueError, match="search_text, act"):
            await client.search()


@respx.mock
async def test_search_refusal_envelope_raises_value_error_and_keeps_token():
    """The portal refuses bad act text with a non-JSON envelope, not a CAPTCHA error."""
    _setup_auth_routes(respx)
    token = "ab" * 32
    respx.post(endpoints.SEARCH_RESULTS_URL).mock(
        return_value=httpx.Response(200, text=f"Act should be characters..! <br/>#####{token}")
    )

    async with JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver()) as client:
        with pytest.raises(ValueError, match="Act should be characters"):
            await client.search("cheque")
        assert client._app_token == token


@respx.mock
async def test_list_acts_filters_debris():
    _setup_auth_routes(respx)
    respx.post(endpoints.GET_DATA_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "res_act1": ["[", "POLICE ACT", " Government Savings Banks Act "],
                "app_token": "t",
            },
        )
    )

    async with JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver()) as client:
        acts = await client.list_acts()

    assert acts == ["POLICE ACT", "Government Savings Banks Act"]
