"""Tests for Judgment Search portal client."""

import httpx
import respx

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.judgments import endpoints
from bharat_courts.judgments.client import JudgmentSearchClient, _validate_pdf_bytes
from bharat_courts.models import JudgmentResult


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


def _make_judgments(n: int) -> list[JudgmentResult]:
    """Create n JudgmentResult with unique PDF URLs."""
    return [
        JudgmentResult(
            title=f"Case {i}",
            court_name="Delhi HC",
            pdf_url=f"https://example.com/pdf/{i}.pdf",
        )
        for i in range(n)
    ]


@respx.mock
async def test_download_pdfs_batch_reset():
    """Test that session resets after batch_size downloads."""
    pdf_content = b"%PDF-1.4 valid pdf content" + b"\x00" * 500
    init_call_count = 0

    def route_get(request: httpx.Request) -> httpx.Response:
        nonlocal init_call_count
        url = str(request.url)
        if "securimage" in url:
            return httpx.Response(200, content=b"captcha-img")
        if "example.com/pdf" in url:
            return httpx.Response(200, content=pdf_content)
        # Main page (init_session)
        init_call_count += 1
        return httpx.Response(200, text="<html></html>")

    respx.get(url__regex=r".*").mock(side_effect=route_get)
    respx.post(endpoints.CHECK_CAPTCHA_URL).mock(
        return_value=httpx.Response(200, json={"captcha_status": "Y", "app_token": "tok"})
    )

    judgments = _make_judgments(30)
    client = JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver())
    async with client:
        result = await client.download_pdfs(judgments, batch_size=25)

    # All 30 should have PDFs
    downloaded = [j for j in result if j.pdf_bytes is not None]
    assert len(downloaded) == 30

    # Session should have been reset once at download #25
    assert init_call_count == 1  # one reset at the batch boundary


@respx.mock
async def test_authenticate_calls_init_session_every_retry():
    """Verify _init_session is called on every CAPTCHA retry attempt, not just once."""
    init_session_count = 0
    captcha_attempt = 0

    def route_get(request: httpx.Request) -> httpx.Response:
        nonlocal init_session_count
        url = str(request.url)
        if "securimage" in url:
            return httpx.Response(200, content=b"captcha-img")
        # Main page (init_session)
        init_session_count += 1
        return httpx.Response(200, text="<html></html>")

    def route_captcha_check(request: httpx.Request) -> httpx.Response:
        nonlocal captcha_attempt
        captcha_attempt += 1
        # Fail first two attempts, succeed on third
        if captcha_attempt < 3:
            return httpx.Response(200, json={"captcha_status": "N", "errormsg": "Wrong"})
        return httpx.Response(200, json={"captcha_status": "Y", "app_token": "tok"})

    respx.get(url__regex=r".*").mock(side_effect=route_get)
    respx.post(endpoints.CHECK_CAPTCHA_URL).mock(side_effect=route_captcha_check)

    client = JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver())
    async with client:
        result = await client._authenticate("test", max_captcha_attempts=3)

    assert result == "abc123"
    # _init_session should be called 3 times (once per attempt)
    assert init_session_count == 3


@respx.mock
async def test_reset_session_for_downloads_uses_authenticate():
    """Verify _reset_session_for_downloads calls _authenticate and resets counter."""
    init_session_count = 0

    def route_get(request: httpx.Request) -> httpx.Response:
        nonlocal init_session_count
        url = str(request.url)
        if "securimage" in url:
            return httpx.Response(200, content=b"captcha-img")
        init_session_count += 1
        return httpx.Response(200, text="<html></html>")

    respx.get(url__regex=r".*").mock(side_effect=route_get)
    respx.post(endpoints.CHECK_CAPTCHA_URL).mock(
        return_value=httpx.Response(200, json={"captcha_status": "Y", "app_token": "tok"})
    )

    client = JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver())
    async with client:
        client._download_count = 25
        ok = await client._reset_session_for_downloads()

    assert ok is True
    assert client._download_count == 0
    assert init_session_count >= 1


@respx.mock
async def test_download_pdfs_skips_already_downloaded():
    """Test that already-downloaded judgments are skipped."""
    pdf_content = b"%PDF-1.4 valid" + b"\x00" * 500
    download_count = 0

    def route_get(request: httpx.Request) -> httpx.Response:
        nonlocal download_count
        url = str(request.url)
        if "example.com/pdf" in url:
            download_count += 1
            return httpx.Response(200, content=pdf_content)
        if "securimage" in url:
            return httpx.Response(200, content=b"captcha-img")
        return httpx.Response(200, text="<html></html>")

    respx.get(url__regex=r".*").mock(side_effect=route_get)
    respx.post(endpoints.CHECK_CAPTCHA_URL).mock(
        return_value=httpx.Response(200, json={"captcha_status": "Y", "app_token": "tok"})
    )

    judgments = _make_judgments(3)
    judgments[1].pdf_bytes = b"%PDF-already-downloaded" + b"\x00" * 500

    client = JudgmentSearchClient(captcha_solver=_FixedCaptchaSolver())
    async with client:
        await client.download_pdfs(judgments)

    # Only 2 downloads (index 0 and 2), index 1 was skipped
    assert download_count == 2
