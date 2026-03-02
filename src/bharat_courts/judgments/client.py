"""Judgment search portal client.

Provides async access to judgments.ecourts.gov.in for searching
High Court judgments by keyword with CAPTCHA solving.

Flow:
1. Load main page (establishes session cookies)
2. Fetch + solve CAPTCHA
3. Validate CAPTCHA via AJAX
4. Load search results page with validated session
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.captcha.manual import ManualCaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config
from bharat_courts.http import RateLimitedClient
from bharat_courts.judgments import endpoints
from bharat_courts.judgments.parser import parse_judgment_search
from bharat_courts.models import JudgmentResult, SearchResult

logger = logging.getLogger(__name__)

# Known bad PDF sizes from the judgment portal:
# 0 bytes = empty response, 315 bytes = error page served as PDF
_BAD_PDF_SIZES = frozenset({0, 315})
_PDF_MAGIC = b"%PDF"


def _validate_pdf_bytes(content: bytes) -> bytes | None:
    """Validate that downloaded content is a real PDF.

    Returns the content if valid, None otherwise.
    """
    if len(content) in _BAD_PDF_SIZES:
        logger.warning("Invalid PDF: got %d bytes (known bad size)", len(content))
        return None
    if not content.startswith(_PDF_MAGIC):
        logger.warning("Invalid PDF: missing %%PDF magic bytes (got %r)", content[:8])
        return None
    return content


class JudgmentSearchClient:
    """Async client for Judgment Search portal (judgments.ecourts.gov.in).

    Usage::

        from bharat_courts.captcha.manual import ManualCaptchaSolver

        async with JudgmentSearchClient() as client:
            results = await client.search("constitution")
            for judgment in results.items:
                print(judgment.title, judgment.judgment_date)
    """

    def __init__(
        self,
        config: BharatCourtsConfig | None = None,
        captcha_solver: CaptchaSolver | None = None,
        http_client: RateLimitedClient | None = None,
    ):
        self._config = config or default_config
        self._captcha_solver = captcha_solver or ManualCaptchaSolver()
        self._http = http_client or RateLimitedClient(self._config)
        self._owns_http = http_client is None
        self._app_token: str = ""
        self._download_count: int = 0

    async def __aenter__(self):
        await self._http.__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._owns_http:
            await self._http.__aexit__(*args)

    def _update_token_from_response(self, data: dict) -> None:
        """Extract and store the rotating app_token from an API response."""
        token = data.get("app_token", "")
        if token:
            self._app_token = token

    def _is_session_expired(self, data: dict) -> bool:
        """Check if the session has expired and needs a full refresh."""
        if data.get("session_expire") == "Y":
            return True
        msg = data.get("errormsg", "")
        if msg and "session" in msg.lower():
            return True
        return False

    async def _init_session(self):
        """Load the main page to establish session cookies."""
        await self._http.get(endpoints.MAIN_PAGE_URL)

    async def _solve_captcha(self) -> str:
        """Fetch and solve a CAPTCHA from the portal."""
        resp = await self._http.get(endpoints.CAPTCHA_IMAGE_URL)
        return await self._captcha_solver.solve(resp.content)

    async def _validate_captcha(self, captcha: str, search_text: str) -> bool:
        """Validate the CAPTCHA via the portal's AJAX endpoint.

        Returns True if valid, False otherwise. Sets self._app_token on success.
        """
        form_body = endpoints.check_captcha_form(
            captcha=captcha,
            search_text=search_text,
        )
        resp = await self._http.post(
            endpoints.CHECK_CAPTCHA_URL,
            content=form_body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        try:
            data = resp.json()
        except Exception:
            logger.error("CAPTCHA check returned non-JSON: %s", resp.text[:200])
            return False

        self._update_token_from_response(data)

        if data.get("captcha_status") == "Y":
            return True

        logger.warning("CAPTCHA failed: %s", data.get("errormsg", "Unknown"))
        return False

    async def _authenticate(self, search_text: str, *, max_captcha_attempts: int = 3) -> str | None:
        """Establish session and solve CAPTCHA. Returns captcha text or None."""
        await self._init_session()
        for attempt in range(max_captcha_attempts):
            captcha_text = await self._solve_captcha()
            if not captcha_text:
                logger.warning("Empty CAPTCHA response, attempt %d", attempt + 1)
                continue
            if await self._validate_captcha(captcha_text, search_text):
                return captcha_text
            logger.info("CAPTCHA attempt %d failed, retrying...", attempt + 1)
        logger.error("Failed to solve CAPTCHA after %d attempts", max_captcha_attempts)
        return None

    async def search(
        self,
        search_text: str,
        *,
        page: int = 1,
        search_opt: str = "PHRASE",
        court_type: str = "2",
        max_captcha_attempts: int = 3,
    ) -> SearchResult:
        """Search for judgments by keyword.

        The portal requires solving a CAPTCHA before each search.
        The captcha_solver configured on this client will be invoked.

        Args:
            search_text: Keywords to search for.
            page: Page number (1-indexed).
            search_opt: "PHRASE" (exact), "ANY" (any word), "ALL" (all words).
            court_type: "2" for High Courts, "3" for SCR.
            max_captcha_attempts: Max CAPTCHA solve retries before giving up.

        Returns:
            SearchResult with list of JudgmentResult items.
        """
        captcha_text = await self._authenticate(
            search_text, max_captcha_attempts=max_captcha_attempts
        )
        if captcha_text is None:
            return SearchResult()

        params = endpoints.search_results_params(
            search_text=search_text,
            captcha=captcha_text,
            search_opt=search_opt,
            court_type=court_type,
            app_token=self._app_token,
            pagenum=page,
        )
        resp = await self._http.get(endpoints.SEARCH_RESULTS_URL, params=params)
        return parse_judgment_search(
            resp.text,
            base_url=endpoints.BASE_URL,
            page=page,
        )

    async def search_all(
        self,
        search_text: str,
        *,
        search_opt: str = "PHRASE",
        court_type: str = "2",
        max_captcha_attempts: int = 3,
    ) -> AsyncIterator[SearchResult]:
        """Iterate through all pages of search results.

        Yields one SearchResult per page, automatically handling
        pagination and token rotation between pages.
        Re-authenticates on session expiry.

        Args:
            search_text: Keywords to search for.
            search_opt: "PHRASE" (exact), "ANY" (any word), "ALL" (all words).
            court_type: "2" for High Courts, "3" for SCR.
            max_captcha_attempts: Max CAPTCHA solve retries before giving up.
        """
        captcha_text = await self._authenticate(
            search_text, max_captcha_attempts=max_captcha_attempts
        )
        if captcha_text is None:
            return

        page = 1
        while True:
            params = endpoints.search_results_params(
                search_text=search_text,
                captcha=captcha_text,
                search_opt=search_opt,
                court_type=court_type,
                app_token=self._app_token,
                pagenum=page,
            )
            resp = await self._http.get(endpoints.SEARCH_RESULTS_URL, params=params)

            # Check for JSON session expiry response
            try:
                data = resp.json()
                self._update_token_from_response(data)
                if self._is_session_expired(data):
                    logger.info("Session expired at page %d, re-authenticating", page)
                    captcha_text = await self._authenticate(
                        search_text, max_captcha_attempts=max_captcha_attempts
                    )
                    if captcha_text is None:
                        return
                    continue
            except Exception:
                pass  # Not JSON — it's HTML results, continue parsing

            result = parse_judgment_search(
                resp.text,
                base_url=endpoints.BASE_URL,
                page=page,
            )
            yield result

            if not result.has_next or not result.items:
                break
            page += 1

    async def download_pdf(self, judgment: JudgmentResult) -> JudgmentResult:
        """Download the PDF for a judgment result.

        Modifies the judgment in-place, setting pdf_bytes only if
        the downloaded content is a valid PDF.
        """
        if not judgment.pdf_url:
            logger.warning("No PDF URL for judgment: %s", judgment.title)
            return judgment

        content = await self._http.get_bytes(judgment.pdf_url)
        validated = _validate_pdf_bytes(content)
        if validated is None:
            logger.warning("Skipping invalid PDF for: %s", judgment.title)
        else:
            judgment.pdf_bytes = validated
            self._download_count += 1
        return judgment

    async def _reset_session_for_downloads(self) -> bool:
        """Reset the session to avoid per-download CAPTCHAs.

        After 25 PDF downloads, the portal starts requiring a CAPTCHA
        per download. Resetting the session avoids this.

        Returns True if reset succeeded, False otherwise.
        """
        self._download_count = 0
        await self._init_session()
        captcha_text = await self._solve_captcha()
        if not captcha_text:
            return False
        return await self._validate_captcha(captcha_text, "")

    async def download_pdfs(
        self,
        judgments: list[JudgmentResult],
        *,
        batch_size: int = 25,
    ) -> list[JudgmentResult]:
        """Download PDFs for multiple judgments in batches.

        Resets the session every ``batch_size`` downloads to avoid
        per-download CAPTCHAs. Skips judgments that already have pdf_bytes.

        Args:
            judgments: List of JudgmentResult to download PDFs for.
            batch_size: Number of downloads before resetting session (default 25).

        Returns:
            The same list of judgments, with pdf_bytes populated where successful.
        """
        pending = [j for j in judgments if j.pdf_url and j.pdf_bytes is None]
        if not pending:
            return judgments

        for i, judgment in enumerate(pending):
            # Reset session at batch boundaries
            if self._download_count > 0 and self._download_count % batch_size == 0:
                logger.info("Reached %d downloads, resetting session", self._download_count)
                if not await self._reset_session_for_downloads():
                    logger.error("Session reset failed, stopping downloads")
                    break

            await self.download_pdf(judgment)
            if judgment.pdf_bytes:
                logger.debug("Downloaded %d/%d: %s", i + 1, len(pending), judgment.title)

        return judgments
