"""Tests for Judgment Search portal client."""

import httpx
import respx

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.judgments import endpoints
from bharat_courts.judgments.client import JudgmentSearchClient, _validate_pdf_bytes


class _FixedCaptchaSolver(CaptchaSolver):
    """Test solver that always returns a fixed string."""

    async def solve(self, image_bytes: bytes) -> str:
        return "abc123"


class TestValidatePdfBytes:
    def test_valid_pdf(self):
        content = b"%PDF-1.4 some pdf content here" + b"\x00" * 500
        assert _validate_pdf_bytes(content) == content

    def test_empty_response(self):
        assert _validate_pdf_bytes(b"") is None

    def test_315_byte_error_page(self):
        content = b"x" * 315
        assert _validate_pdf_bytes(content) is None

    def test_non_pdf_content(self):
        content = b"<html>Not Found</html>" + b"\x00" * 500
        assert _validate_pdf_bytes(content) is None

    def test_minimal_valid_pdf(self):
        content = b"%PDF-1.7" + b"\x00" * 400
        assert _validate_pdf_bytes(content) == content


class TestTokenRotation:
    def _make_client(self) -> JudgmentSearchClient:
        from bharat_courts.captcha.manual import ManualCaptchaSolver

        return JudgmentSearchClient(captcha_solver=ManualCaptchaSolver())

    def test_update_token_from_response(self):
        client = self._make_client()
        assert client._app_token == ""
        client._update_token_from_response({"app_token": "tok_abc123"})
        assert client._app_token == "tok_abc123"

    def test_update_token_ignores_empty(self):
        client = self._make_client()
        client._app_token = "existing"
        client._update_token_from_response({"app_token": ""})
        assert client._app_token == "existing"

    def test_update_token_missing_key(self):
        client = self._make_client()
        client._app_token = "existing"
        client._update_token_from_response({})
        assert client._app_token == "existing"

    def test_is_session_expired_yes(self):
        client = self._make_client()
        assert client._is_session_expired({"session_expire": "Y"}) is True

    def test_is_session_expired_no(self):
        client = self._make_client()
        assert client._is_session_expired({"session_expire": "N"}) is False
        assert client._is_session_expired({}) is False

    def test_is_session_expired_error_message(self):
        client = self._make_client()
        assert client._is_session_expired({"errormsg": "Session expired"}) is True
        assert client._is_session_expired({"errormsg": "Invalid captcha"}) is False


def _make_results_html(title: str, has_next: bool) -> str:
    next_link = '<a href="?page=2" class="next">Next</a>' if has_next else ""
    return f"""
    <table id="resultTable">
      <tr><th>Sr</th><th>J</th><th>Case</th><th>Court</th><th>Judge</th><th>Date</th><th>DL</th></tr>
      <tr>
        <td>1</td><td>Judgment</td>
        <td><strong>{title}</strong><br>WP/1/2024</td>
        <td>Delhi HC</td><td>Single Bench</td><td>01-01-2024</td>
        <td><a href="/pdf/1.pdf">PDF</a></td>
      </tr>
    </table>
    <div class="pagination">
      <span>Showing 1 to 1 of 2 entries</span>
      {next_link}
    </div>
    """


def _setup_respx_for_search(mock: respx.MockRouter, results_side_effect=None) -> None:
    """Configure respx routes for a typical search flow.

    Note: MAIN_PAGE_URL and SEARCH_RESULTS_URL share the same base URL,
    so we use a single side_effect that checks for the 'p' query param
    to distinguish search requests from session init.
    """
    mock.get(endpoints.CAPTCHA_IMAGE_URL).mock(
        return_value=httpx.Response(200, content=b"fake-captcha-png")
    )
    mock.post(endpoints.CHECK_CAPTCHA_URL).mock(
        return_value=httpx.Response(200, json={"captcha_status": "Y", "app_token": "tok1"})
    )

    def _route_get(request: httpx.Request) -> httpx.Response:
        if "p" in dict(request.url.params):
            if results_side_effect:
                return results_side_effect(request)
            return httpx.Response(200, text="<html></html>")
        # init_session — no query params
        return httpx.Response(200, text="<html></html>")

    mock.get(endpoints.MAIN_PAGE_URL).mock(side_effect=_route_get)


@respx.mock
async def test_search_with_page():
    page_html = _make_results_html("Case A", has_next=False)
    _setup_respx_for_search(respx, lambda req: httpx.Response(200, text=page_html))

    client = JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver())
    async with client:
        result = await client.search("test", page=2)
    assert result.page == 2
    assert len(result.items) == 1
    assert result.items[0].title == "Case A"


@respx.mock
async def test_search_all_two_pages():
    page1_html = _make_results_html("Page 1 Case", has_next=True)
    page2_html = _make_results_html("Page 2 Case", has_next=False)

    def results_side_effect(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        if params.get("pagenum", "1") == "1":
            return httpx.Response(200, text=page1_html)
        return httpx.Response(200, text=page2_html)

    _setup_respx_for_search(respx, results_side_effect)

    client = JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver())
    async with client:
        pages = []
        async for result in client.search_all("test"):
            pages.append(result)

    assert len(pages) == 2
    assert pages[0].items[0].title == "Page 1 Case"
    assert pages[0].page == 1
    assert pages[1].items[0].title == "Page 2 Case"
    assert pages[1].page == 2
