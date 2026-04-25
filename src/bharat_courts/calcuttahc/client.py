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

import httpx

from bharat_courts.calcuttahc import endpoints
from bharat_courts.calcuttahc.parser import parse_search_response, to_case_orders
from bharat_courts.captcha import default_solver
from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config
from bharat_courts.http import RateLimitedClient, create_legacy_ssl_context
from bharat_courts.models import CaseInfo, CaseOrder

logger = logging.getLogger(__name__)


class CalcuttaHCClient:
    """Async client for Calcutta High Court (calcuttahighcourt.gov.in).

    Provides order/judgment search and PDF download for cases
    from September 2020 onwards (CIS system).

    Usage::

        async with CalcuttaHCClient() as client:
            case_info, orders = await client.search_orders(
                case_type="12", case_number="12886", year="2024",
            )
            if case_info:
                print(case_info.case_number, case_info.petitioner, "vs", case_info.respondent)
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
            self._http = RateLimitedClient(self._config, ssl_context=create_legacy_ssl_context())
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
        max_captcha_attempts: int = 5,
    ) -> tuple[CaseInfo | None, list[CaseOrder]]:
        """Search for orders/judgments by case number.

        Args:
            case_type: Numeric case type code (e.g. "12" for WPA).
            case_number: Case registration number (e.g. "12886").
            year: Case year (e.g. "2024").
            establishment: Bench name — "appellate", "original",
                "jalpaiguri", or "portblair".
            max_captcha_attempts: Max CAPTCHA solve retries. Default 5
                (with OCR ~75% accuracy this gives ~0.1% all-fail rate;
                each retry opens a fresh session, ~3-4s overhead).

        Returns:
            Tuple of ``(CaseInfo | None, list[CaseOrder])``. The
            ``CaseInfo`` carries case-level metadata (CNR, parties,
            full case number); the list carries per-order rows. If no
            case matched and no metadata could be recovered, returns
            ``(None, [])``.
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
            try:
                resp = await self._http.post(
                    endpoints.SEARCH_URL,
                    data=form,
                    headers={
                        "X-Requested-With": "XMLHttpRequest",
                        "Referer": endpoints.SEARCH_PAGE_URL,
                    },
                )
            except httpx.HTTPStatusError as e:
                # Wrong CAPTCHA → the portal returns 422 with a Laravel
                # validation body. Rotate session and retry. Other 4xx
                # (real validation errors) propagate.
                if e.response.status_code == 422:
                    logger.warning("CAPTCHA attempt %d failed (422)", attempt + 1)
                    continue
                raise

            try:
                search_data = parse_search_response(resp.text)
                break
            except Exception as e:
                logger.warning("Failed to parse response on attempt %d: %s", attempt + 1, e)
                continue

        if search_data is None:
            logger.error("Failed to search after %d attempts", max_captcha_attempts)
            return None, []

        case_info = _build_case_info(search_data)

        if not search_data["orders"]:
            if case_info is None:
                return None, []
            return case_info, []

        # Resolve PDF URLs for each order via /show_pdf
        pdf_urls: dict[str, str] = {}
        for order in search_data["orders"]:
            order_data = order.get("order_data", "")
            if not order_data:
                continue
            try:
                pdf_form = endpoints.show_pdf_form(token=self._csrf_token, order_data=order_data)
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

        return case_info, to_case_orders(search_data, pdf_urls)

    async def download_order_pdf(self, pdf_url: str) -> bytes:
        """Download an order/judgment PDF.

        Args:
            pdf_url: URL from CaseOrder.pdf_url.

        Returns:
            Raw PDF bytes.

        Raises:
            RuntimeError: if the response does not start with the
                ``%PDF`` magic bytes (e.g. portal returned an error
                string instead of a PDF).
        """
        resp = await self._http.get(
            pdf_url,
            headers={"Referer": endpoints.SEARCH_PAGE_URL},
        )
        content = resp.content
        if content[:4] != b"%PDF":
            raise RuntimeError(
                f"PDF download did not return a valid PDF "
                f"(got {len(content)} bytes; head={content[:64]!r})"
            )
        return content


def _build_case_info(search_data: dict) -> CaseInfo | None:
    """Build a CaseInfo from parsed search response metadata.

    Returns None if the response carries no usable case-level metadata
    (no CNR and no full case number).
    """
    cino = search_data.get("cino", "")
    full_case_num = search_data.get("full_case_num", "")
    if not cino and not full_case_num:
        return None

    side = search_data.get("side", "").strip()
    # The portal's `side` field already contains the court name, e.g.
    # "Calcutta High Court - Appellate Side". Use it as-is when present;
    # fall back to the bare court name otherwise.
    court_name = side or "Calcutta High Court"

    return CaseInfo(
        case_number=full_case_num,
        case_type=search_data.get("case_type_name", ""),
        cnr_number=cino,
        petitioner=search_data.get("petitioner", ""),
        respondent=search_data.get("respondent", ""),
        court_name=court_name,
    )
