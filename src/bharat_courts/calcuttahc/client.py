"""Calcutta High Court portal client.

Provides async access to calcuttahighcourt.gov.in for searching
orders and judgments by case number with PDF download.

Covers cases from September 2020 onwards (CIS system).

Flow:
1. GET /highcourt_order_search — HTML page with CSRF token + session cookie
2. GET /captcha/default — CAPTCHA image
3. POST /order_judgment_search — JSON with case info + order table HTML
4. POST /show_pdf — resolves order_data to a PDF URL
5. GET {pdf_url} — download PDF (no auth needed)
"""

from __future__ import annotations

import logging
import re

from bharat_courts.calcuttahc import endpoints
from bharat_courts.calcuttahc.parser import parse_search_response, to_case_orders
from bharat_courts.captcha import default_solver
from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config
from bharat_courts.http import RateLimitedClient, create_legacy_ssl_context
from bharat_courts.models import CaseOrder

logger = logging.getLogger(__name__)


class CalcuttaHCClient:
    """Async client for Calcutta High Court (calcuttahighcourt.gov.in).

    Provides order/judgment search and PDF download for cases
    from September 2020 onwards (CIS system).

    Usage::

        async with CalcuttaHCClient() as client:
            orders = await client.search_orders(
                case_type="12", case_number="12886", year="2024",
            )
            for order in orders:
                print(order.order_date, order.judge, order.neutral_citation)
                if order.pdf_url:
                    pdf = await client.download_order_pdf(order.pdf_url)
    """

    def __init__(
        self,
        config: BharatCourtsConfig | None = None,
        captcha_solver: CaptchaSolver | None = None,
        http_client: RateLimitedClient | None = None,
    ):
        self._config = config or default_config
        self._captcha_solver = captcha_solver or default_solver()
        if http_client:
            self._http = http_client
            self._owns_http = False
        else:
            self._http = RateLimitedClient(
                self._config, ssl_context=create_legacy_ssl_context()
            )
            self._owns_http = True
        self._csrf_token: str = ""

    async def __aenter__(self):
        await self._http.__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._owns_http:
            await self._http.__aexit__(*args)

    async def _init_session(self) -> str:
        """Load the search page to establish session cookie and get CSRF token.

        Returns:
            The CSRF token string.
        """
        resp = await self._http.get(
            endpoints.SEARCH_PAGE_URL,
            headers={"Referer": endpoints.BASE_URL + "/"},
        )
        match = re.search(r'name="_token" value="([^"]+)"', resp.text)
        if not match:
            raise RuntimeError("Could not extract CSRF token from search page")
        self._csrf_token = match.group(1)
        logger.debug("Session init: got CSRF token %s...", self._csrf_token[:12])
        return self._csrf_token

    async def _solve_captcha(self) -> str:
        """Fetch and solve a CAPTCHA from the portal."""
        resp = await self._http.get(
            endpoints.CAPTCHA_URL,
            headers={"Referer": endpoints.SEARCH_PAGE_URL},
        )
        return await self._captcha_solver.solve(resp.content)

    async def search_orders(
        self,
        *,
        case_type: str,
        case_number: str,
        year: str,
        establishment: str = "appellate",
        max_captcha_attempts: int = 3,
    ) -> list[CaseOrder]:
        """Search for orders/judgments by case number.

        Args:
            case_type: Numeric case type code (e.g. "12" for WPA).
            case_number: Case registration number (e.g. "12886").
            year: Case year (e.g. "2024").
            establishment: Bench name — "appellate", "original",
                "jalpaiguri", or "portblair".
            max_captcha_attempts: Max CAPTCHA solve retries.

        Returns:
            List of CaseOrder objects with pdf_url and neutral_citation.
        """
        est_code = endpoints.ESTABLISHMENTS.get(establishment.lower(), establishment)

        # CAPTCHA retry loop — fresh session each attempt
        search_data = None
        for attempt in range(max_captcha_attempts):
            if attempt > 0:
                logger.info("CAPTCHA retry %d/%d — new session", attempt + 1, max_captcha_attempts)

            token = await self._init_session()
            captcha = await self._solve_captcha()

            form = endpoints.search_form(
                token=token,
                establishment=est_code,
                case_type=case_type,
                case_number=case_number,
                year=year,
                captcha=captcha,
            )
            resp = await self._http.post(
                endpoints.SEARCH_URL,
                data=form,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": endpoints.SEARCH_PAGE_URL,
                },
            )

            if resp.status_code == 422:
                logger.warning("CAPTCHA attempt %d failed (422)", attempt + 1)
                continue

            try:
                search_data = parse_search_response(resp.text)
                break
            except Exception as e:
                logger.warning("Failed to parse response on attempt %d: %s", attempt + 1, e)
                continue

        if search_data is None:
            logger.error("Failed to search after %d attempts", max_captcha_attempts)
            return []

        if not search_data["orders"]:
            return []

        # Resolve PDF URLs for each order via /show_pdf
        pdf_urls: dict[str, str] = {}
        for order in search_data["orders"]:
            order_data = order.get("order_data", "")
            if not order_data:
                continue
            try:
                pdf_form = endpoints.show_pdf_form(
                    token=self._csrf_token, order_data=order_data
                )
                pdf_resp = await self._http.post(
                    endpoints.SHOW_PDF_URL,
                    data=pdf_form,
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": endpoints.SEARCH_PAGE_URL,
                    },
                )
                pdf_url = pdf_resp.text.strip()
                if pdf_url.startswith("http"):
                    pdf_urls[order_data] = pdf_url
                    logger.debug("Resolved PDF: %s", pdf_url)
            except Exception as e:
                logger.warning("Failed to resolve PDF for order %s: %s", order_data, e)

        return to_case_orders(search_data, pdf_urls)

    async def download_order_pdf(self, pdf_url: str) -> bytes:
        """Download an order/judgment PDF.

        Args:
            pdf_url: URL from CaseOrder.pdf_url.

        Returns:
            Raw PDF bytes.
        """
        resp = await self._http.get(
            pdf_url,
            headers={"Referer": endpoints.SEARCH_PAGE_URL},
        )
        return resp.content
