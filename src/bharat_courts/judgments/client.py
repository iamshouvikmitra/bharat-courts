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

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.captcha.manual import ManualCaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config
from bharat_courts.http import RateLimitedClient
from bharat_courts.judgments import endpoints
from bharat_courts.judgments.parser import parse_judgment_search
from bharat_courts.models import JudgmentResult, SearchResult

logger = logging.getLogger(__name__)


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

    async def __aenter__(self):
        await self._http.__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._owns_http:
            await self._http.__aexit__(*args)

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

        self._app_token = data.get("app_token", "")

        if data.get("captcha_status") == "Y":
            return True

        logger.warning("CAPTCHA failed: %s", data.get("errormsg", "Unknown"))
        return False

    async def search(
        self,
        search_text: str,
        *,
        search_opt: str = "PHRASE",
        court_type: str = "2",
        max_captcha_attempts: int = 3,
    ) -> SearchResult:
        """Search for judgments by keyword.

        The portal requires solving a CAPTCHA before each search.
        The captcha_solver configured on this client will be invoked.

        Args:
            search_text: Keywords to search for.
            search_opt: "PHRASE" (exact), "ANY" (any word), "ALL" (all words).
            court_type: "2" for High Courts, "3" for SCR.
            max_captcha_attempts: Max CAPTCHA solve retries before giving up.

        Returns:
            SearchResult with list of JudgmentResult items.
        """
        # Step 1: Establish session
        await self._init_session()

        # Step 2: CAPTCHA loop
        for attempt in range(max_captcha_attempts):
            captcha_text = await self._solve_captcha()
            if not captcha_text:
                logger.warning("Empty CAPTCHA response, attempt %d", attempt + 1)
                continue

            if await self._validate_captcha(captcha_text, search_text):
                break
            logger.info("CAPTCHA attempt %d failed, retrying...", attempt + 1)
        else:
            logger.error("Failed to solve CAPTCHA after %d attempts", max_captcha_attempts)
            return SearchResult()

        # Step 3: Load search results
        params = endpoints.search_results_params(
            search_text=search_text,
            captcha=captcha_text,
            search_opt=search_opt,
            court_type=court_type,
            app_token=self._app_token,
        )
        resp = await self._http.get(endpoints.SEARCH_RESULTS_URL, params=params)
        return parse_judgment_search(
            resp.text,
            base_url=endpoints.BASE_URL,
        )

    async def download_pdf(self, judgment: JudgmentResult) -> JudgmentResult:
        """Download the PDF for a judgment result.

        Modifies the judgment in-place, setting pdf_bytes.
        """
        if not judgment.pdf_url:
            logger.warning("No PDF URL for judgment: %s", judgment.title)
            return judgment

        judgment.pdf_bytes = await self._http.get_bytes(judgment.pdf_url)
        return judgment
