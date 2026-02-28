"""HC Services portal client.

Provides async access to hcservices.ecourts.gov.in for:
- Case status lookup (by case number, party name, advocate, etc.)
- Court orders
- Cause list

Flow:
1. GET main.php — establishes session, loads state/court config
2. GET securimage/securimage_show.php — fetches CAPTCHA
3. POST cases_qry/index_qry.php?action_code=showRecords — search query
4. POST cases_qry/o_civil_case_history.php — case details
"""

from __future__ import annotations

import logging

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.captcha.manual import ManualCaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config
from bharat_courts.hcservices import endpoints
from bharat_courts.hcservices.parser import (
    CaptchaError,
    parse_case_status,
    parse_cause_list,
    parse_orders,
)
from bharat_courts.http import RateLimitedClient
from bharat_courts.models import CaseInfo, CaseOrder, CauseListPDF, Court

logger = logging.getLogger(__name__)


class HCServicesClient:
    """Async client for HC Services (hcservices.ecourts.gov.in).

    Usage::

        async with HCServicesClient() as client:
            cases = await client.case_status(
                court=get_court("delhi"),
                case_type="WP(C)",
                case_number="12345",
                year="2024",
            )
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

    async def __aenter__(self):
        await self._http.__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._owns_http:
            await self._http.__aexit__(*args)

    async def _init_session(self):
        """Load the main page to establish session cookies.

        Must be called once before any other request to obtain a valid
        PHP session (HCSERVICES_SESSID cookie).
        """
        resp = await self._http.get(
            endpoints.MAIN_PAGE_URL,
            headers={"Referer": endpoints.BASE_URL + "/"},
        )
        logger.debug("Session init: status=%d", resp.status_code)

    async def _solve_captcha(self) -> str:
        """Fetch a fresh CAPTCHA and solve it.

        A fresh session (``_init_session``) must be called first so that the
        Securimage backend has a valid PHP session to bind the captcha to.
        """
        resp = await self._http.get(
            endpoints.CAPTCHA_IMAGE_URL,
            headers={"Referer": endpoints.MAIN_PAGE_URL},
        )
        return await self._captcha_solver.solve(resp.content)

    async def _post_with_captcha_retry(self, url: str, form_builder, *, max_retries: int = 3):
        """POST with automatic CAPTCHA retry on CaptchaError.

        Each retry creates a brand-new session so the Securimage backend
        generates a fresh CAPTCHA (within a single session the image is
        pinned to the same challenge).

        Args:
            url: Target URL.
            form_builder: Callable(captcha: str) -> dict of form data.
            max_retries: Number of attempts.

        Returns:
            httpx.Response on success.

        Raises:
            CaptchaError: If all retries fail.
        """
        for attempt in range(max_retries):
            if attempt > 0:
                logger.info("CAPTCHA retry %d/%d — new session", attempt + 1, max_retries)
            await self._init_session()
            captcha = await self._solve_captcha()
            form = form_builder(captcha)
            resp = await self._http.post(
                url,
                data=form,
                headers={"Referer": endpoints.MAIN_PAGE_URL},
            )
            # Quick-check for captcha error before full parse
            text = resp.text.strip().lstrip("\ufeff")
            if '"Invalid Captcha"' in text or '"con":"Invalid Captcha"' in text:
                logger.warning("CAPTCHA attempt %d failed (invalid)", attempt + 1)
                continue
            return resp
        raise CaptchaError(f"CAPTCHA failed after {max_retries} attempts")

    async def case_status(
        self,
        court: Court,
        *,
        case_type: str,
        case_number: str,
        year: str,
        bench_code: str = "1",
    ) -> list[CaseInfo]:
        """Look up case status by case number.

        Args:
            court: Court object (use get_court() to obtain).
            case_type: Numeric case type code (e.g. "134" for W.P.(C) in Delhi).
                Use :meth:`list_case_types` to discover available codes.
            case_number: Case number without type/year.
            year: Registration year (e.g. "2024").
            bench_code: Bench code from :meth:`list_benches` (default "1").

        Returns:
            List of matching CaseInfo objects.
        """

        def build_form(captcha: str) -> dict:
            return endpoints.case_status_form(
                state_code=court.state_code,
                court_code=bench_code,
                case_type=case_type,
                case_number=case_number,
                year=year,
                captcha=captcha,
            )

        resp = await self._post_with_captcha_retry(endpoints.SHOW_RECORDS_URL, build_form)
        results = parse_case_status(resp.text)
        for r in results:
            r.court_name = court.name
        return results

    async def case_status_by_party(
        self,
        court: Court,
        *,
        party_name: str,
        year: str,
        bench_code: str = "1",
        status_filter: str = "Both",
    ) -> list[CaseInfo]:
        """Search cases by party name.

        Args:
            court: Court object.
            party_name: Petitioner or respondent name (min 3 chars).
            year: Registration year (**mandatory**, e.g. "2024").
            bench_code: Bench code from :meth:`list_benches` (default "1").
            status_filter: "Pending", "Disposed", or "Both".

        Returns:
            List of matching CaseInfo objects.
        """

        def build_form(captcha: str) -> dict:
            return endpoints.case_status_by_party_form(
                state_code=court.state_code,
                court_code=bench_code,
                petres_name=party_name,
                rgyear=year,
                captcha=captcha,
                status_filter=status_filter,
            )

        resp = await self._post_with_captcha_retry(endpoints.SHOW_RECORDS_URL, build_form)
        results = parse_case_status(resp.text)
        for r in results:
            r.court_name = court.name
        return results

    async def court_orders(
        self,
        court: Court,
        *,
        case_type: str,
        case_number: str,
        year: str,
        bench_code: str = "1",
    ) -> list[CaseOrder]:
        """Get court orders for a case.

        Args:
            court: Court object.
            case_type: Numeric case type code (e.g. "134").
            case_number: Case number.
            year: Registration year.
            bench_code: Bench code from :meth:`list_benches` (default "1").

        Returns:
            List of CaseOrder objects.
        """

        def build_form(captcha: str) -> dict:
            return endpoints.court_orders_form(
                state_code=court.state_code,
                court_code=bench_code,
                case_type=case_type,
                case_number=case_number,
                year=year,
                captcha=captcha,
            )

        resp = await self._post_with_captcha_retry(endpoints.SHOW_RECORDS_URL, build_form)
        return parse_orders(resp.text, base_url=endpoints.BASE_URL)

    async def cause_list(
        self,
        court: Court,
        *,
        civil: bool = True,
        bench_code: str = "1",
        causelist_date: str = "",
    ) -> list[CauseListPDF]:
        """Get cause list PDFs for a court.

        The HC Services portal returns a table of PDF links, one per bench/judge.
        Each entry contains the bench name, cause list type, and PDF URL.

        Args:
            court: Court object.
            civil: True for civil cases, False for criminal.
            bench_code: Bench code from list_benches() (default "1" = principal).
            causelist_date: Date in DD-MM-YYYY format (defaults to today).

        Returns:
            List of CauseListPDF objects with bench info and PDF URLs.
        """
        # Determine selprevdays: "1" if date is in the past, "0" otherwise
        selprevdays = "0"
        if causelist_date:
            from datetime import date, datetime

            try:
                sel = datetime.strptime(causelist_date, "%d-%m-%Y").date()
                if sel < date.today():
                    selprevdays = "1"
            except ValueError:
                pass

        def build_form(captcha: str) -> dict:
            return endpoints.cause_list_form(
                state_code=court.state_code,
                court_code=bench_code,
                captcha=captcha,
                causelist_date=causelist_date,
                flag="civ_t" if civil else "cri_t",
                selprevdays=selprevdays,
            )

        resp = await self._post_with_captcha_retry(endpoints.INDEX_QRY_URL, build_form)
        return parse_cause_list(resp.text, base_url=endpoints.BASE_URL)

    async def list_benches(self, court: Court) -> dict[str, str]:
        """Get available benches for a High Court.

        Returns:
            Dict mapping bench code to bench name, e.g.
            {"1": "Principal Bench at Delhi", "2": "Lucknow Bench"}.
        """
        await self._init_session()
        form = endpoints.fill_bench_form(state_code=court.state_code)
        resp = await self._http.post(endpoints.INDEX_QRY_URL, data=form)
        benches = {}
        for entry in resp.text.split("#"):
            entry = entry.strip()
            if "~" in entry:
                code, name = entry.split("~", 1)
                # Strip BOM (\ufeff) and whitespace from portal response
                code = code.strip().strip("\ufeff")
                name = name.strip().strip("\ufeff")
                if code and code != "0" and name and "select" not in name.lower():
                    benches[code] = name
        return benches

    async def list_case_types(self, court: Court, *, bench_code: str = "1") -> dict[str, str]:
        """Get available case types for a High Court bench.

        Returns:
            Dict mapping case type code to name, e.g.
            {"134": "W.P.(C)(CIVIL WRITS)-134", "27": "W.P.(CRL)..."}.
        """
        await self._init_session()
        form = endpoints.fill_case_type_form(
            state_code=court.state_code,
            court_code=bench_code,
        )
        resp = await self._http.post(endpoints.FILL_CASE_TYPE_URL, data=form)
        case_types = {}
        for entry in resp.text.split("#"):
            entry = entry.strip().strip("\ufeff")
            if "~" in entry:
                code, name = entry.split("~", 1)
                code = code.strip()
                name = name.strip()
                if code and code != "0" and name and "select" not in name.lower():
                    case_types[code] = name
        return case_types

    async def download_order_pdf(self, pdf_url: str) -> bytes:
        """Download an order/judgment PDF.

        Args:
            pdf_url: URL from CaseOrder.pdf_url.

        Returns:
            Raw PDF bytes.
        """
        return await self._http.get_bytes(pdf_url)
