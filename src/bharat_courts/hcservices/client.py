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
import re

from bharat_courts.captcha import default_solver
from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.casedetail import parse_case_detail
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config
from bharat_courts.hcservices import endpoints
from bharat_courts.hcservices.parser import (
    CaptchaError,
    dedupe_by_cnr,
    filter_by_year,
    is_captcha_rejection,
    parse_advocate_cause_list,
    parse_advocate_search,
    parse_case_status,
    parse_cause_list,
    parse_code_name_list,
    parse_orders,
)
from bharat_courts.http import RateLimitedClient
from bharat_courts.models import (
    AdvocateSearch,
    CaseDetail,
    CaseInfo,
    CaseOrder,
    CauseListEntry,
    CauseListPDF,
    Court,
)

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
        self._captcha_solver = captcha_solver or default_solver()
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

    async def _post_with_captcha_retry(self, url: str, form_builder, *, max_retries: int = 5):
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
            if not captcha:
                # The OCR solver discards unusable decodes (wrong length /
                # non-alphanumeric). Sending one anyway earns ERROR_VAL, which
                # this loop doesn't retry on — the whole call then fails on a
                # single bad OCR read (#5). Skip straight to a fresh session.
                logger.warning("CAPTCHA attempt %d skipped (solver returned empty)", attempt + 1)
                continue
            form = form_builder(captcha)
            resp = await self._http.post(
                url,
                data=form,
                headers={"Referer": endpoints.MAIN_PAGE_URL},
            )
            # Quick-check for captcha error before full parse. Uses the same
            # condition the parser raises CaptchaError on, so a reworded
            # rejection is retried here rather than escaping as an exception
            # with every remaining attempt unused.
            if is_captcha_rejection(resp.text):
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

    async def case_status_by_advocate(
        self,
        court: Court,
        *,
        advocate_name: str | None = None,
        bar_code: str | None = None,
        bench_code: str = "1",
        status_filter: str = "Both",
    ) -> list[CaseInfo]:
        """Search an advocate's cases by name or bar registration number.

        Unlike :meth:`case_status_by_party` this needs no year, so a single
        call returns the advocate's whole book — useful for onboarding a
        practice without entering case numbers by hand.

        Prefer the bar code. The portal resolves it to the advocate itself
        and echoes the resolution back in the response's ``adv_name``
        ("G/504/2011" answered with "MR. HEMAL SHAH(6960)"), so the result is
        exact and needs no filtering.

        Name search is a substring match and can pull in other advocates.
        **Filtering it on the bracketed court id silently loses matters**:
        for G/504/2011 the id appears on 6,666 rows but 97 more — 64 further
        CNRs, all filed 2015 and earlier — carry the bare name with no id at
        all. Both searches returned the same 2,779 matters; only the
        id-filtered subset was short.

        Args:
            court: Court object.
            advocate_name: Advocate name, full or partial (min 3 chars).
            bar_code: Bar registration number as ``<STATE>/<NUMBER>/<YEAR>``,
                e.g. "G/504/2011".
            bench_code: Bench code from :meth:`list_benches` (default "1").
            status_filter: "Pending", "Disposed", or "Both".

        Returns:
            List of matching CaseInfo objects. Results are one row per
            party, so a case with several petitioners repeats.

        Raises:
            ValueError: If neither or both of advocate_name / bar_code given.

        See also:
            :meth:`advocate_search`, the same request kept whole. This is a
            thin view over it — call that one directly if you also need to
            know *whether* the portal recognised the advocate, rather than
            spending a second session and CAPTCHA solve to find out.
        """
        result = await self.advocate_search(
            court,
            advocate_name=advocate_name,
            bar_code=bar_code,
            bench_code=bench_code,
            status_filter=status_filter,
        )
        return result.cases

    async def advocate_search(
        self,
        court: Court,
        *,
        advocate_name: str | None = None,
        bar_code: str | None = None,
        bench_code: str = "1",
        status_filter: str = "Both",
    ) -> AdvocateSearch:
        """Search an advocate's cases, keeping who the portal matched.

        The whole of the :meth:`case_status_by_advocate` request — that
        method is now a view over this one, returning only ``.cases`` — so
        the advocate the portal resolved the query to survives alongside the
        cases: ``G/504/2011`` comes back as ``MR. HEMAL SHAH(6960)``.

        That echo is the positive confirmation a bar code is real, and it is
        worth having because "you have no pending matters" reads very
        differently from "that bar number does not exist" to someone who has
        just signed up.

        Measured live: ``G/504/2011`` answered ``found=True``,
        ``name="MR. HEMAL SHAH"``, ``code="6960"``, 2,704 rows, while
        ``G/999999/1999`` raised ``ServerError: ERROR_VAL``.

        **The negative signal is ambiguous, though.** ``ERROR_VAL`` is also
        what a transient refusal looks like — a seeding run saw two dates
        fail that had answered minutes earlier — so a single error does not
        prove a bar code wrong. Retry before telling a lawyer their number is
        invalid; only ``.found`` is unambiguous.

        Returns:
            An :class:`AdvocateSearch`. Check ``.found`` before ``.cases``.

        Raises:
            ValueError: If neither or both of advocate_name / bar_code given.
        """
        # Before the session and the CAPTCHA solve, not inside the retry
        # loop's form_builder — a manual solver blocks on a human at that
        # point, and the request was never going to be buildable.
        endpoints.validate_advocate_query(advocate_name, bar_code)

        def build_form(captcha: str) -> dict:
            return endpoints.case_status_by_advocate_form(
                state_code=court.state_code,
                court_code=bench_code,
                captcha=captcha,
                advocate_name=advocate_name,
                bar_code=bar_code,
                status_filter=status_filter,
            )

        resp = await self._post_with_captcha_retry(endpoints.SHOW_RECORDS_URL, build_form)
        result = parse_advocate_search(resp.text)
        for r in result.cases:
            r.court_name = court.name
        return result

    async def advocate_cause_list(
        self,
        court: Court,
        *,
        bar_code: str,
        causelist_date: str,
        bench_code: str = "1",
    ) -> list[CauseListEntry]:
        """Fetch an advocate's cause list for a given date.

        This is the court's own answer to "what do I have on this date",
        so it needs no matching against a party or advocate name.

        Rows are per-party; pass the result through
        :func:`~bharat_courts.hcservices.parser.dedupe_by_cnr` for one entry
        per case. No item/serial number is returned — that appears only in
        the cause list PDF.

        Args:
            court: Court object.
            bar_code: Bar registration number, e.g. "G/504/2011".
            causelist_date: Listing date as ``DD-MM-YYYY``. The portal
                rejects dates more than one month ahead.
            bench_code: Bench code from :meth:`list_benches` (default "1").

        Returns:
            List of CauseListEntry, one per party per listed case.
        """

        def build_form(captcha: str) -> dict:
            return endpoints.advocate_cause_list_form(
                state_code=court.state_code,
                court_code=bench_code,
                captcha=captcha,
                bar_code=bar_code,
                causelist_date=causelist_date,
            )

        resp = await self._post_with_captcha_retry(endpoints.SHOW_RECORDS_URL, build_form)
        return parse_advocate_cause_list(resp.text)

    async def case_status_by_cnr(self, cnr: str) -> CaseDetail:
        """Look up a case by its CNR number.

        This returns considerably more than :meth:`case_status`: the search
        endpoints answer with identity only, leaving ``status`` and
        ``next_hearing_date`` empty, whereas a CNR lookup returns the whole
        case page — stage, coram, every party with advocates, the acts, the
        full hearing history and the orders — in a single request.

        Args:
            cnr: 16-character CNR, e.g. "GJHC240464312025". Hyphens and
                spaces are stripped.

        Returns:
            A CaseDetail. Sections the case does not have (no orders yet, no
            acts recorded) come back empty rather than raising.

        Raises:
            ValueError: If the CNR is not 16 alphanumeric characters.
            CaptchaError: If every CAPTCHA attempt failed.
        """
        cleaned = re.sub(r"[\s-]", "", cnr).upper()
        if len(cleaned) != 16 or not cleaned.isalnum():
            raise ValueError(f"CNR must be 16 alphanumeric characters, got {cnr!r}")

        def build_form(captcha: str) -> dict:
            return endpoints.case_status_by_cnr_form(cnr=cleaned, captcha=captcha)

        resp = await self._post_with_captcha_retry(endpoints.INDEX_QRY_URL, build_form)
        return parse_case_detail(resp.text, cnr=cleaned, base_url=endpoints.BASE_URL)

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

        Uses a case number search to get the encrypted order URL path,
        then constructs the PDF download URL from display_pdf.php.

        Args:
            court: Court object.
            case_type: Numeric case type code (e.g. "134").
            case_number: Case number.
            year: Registration year.
            bench_code: Bench code from :meth:`list_benches` (default "1").

        Returns:
            List of CaseOrder objects with PDF URLs.
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
        return parse_orders(
            resp.text,
            base_url=endpoints.BASE_URL,
            bench_code=bench_code,
            state_code=court.state_code,
        )

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
        return parse_code_name_list(resp.text)

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
        return parse_code_name_list(resp.text)

    async def list_acts(
        self, court: Court, *, bench_code: str = "1", search: str = ""
    ) -> dict[str, str]:
        """Get the acts a High Court bench files cases under.

        Needs no CAPTCHA. The codes are **local to the court** and not
        portable: IPC is ``"1"`` ("INDIAN PENAL CODE") in Delhi but ``"535"``
        ("PENAL CODE, 1860") in Gujarat, and one act can appear under
        several codes \u2014 Delhi lists five for arbitration. Look codes up per
        court rather than reusing them.

        Args:
            court: Court object.
            bench_code: Bench code from :meth:`list_benches` (default "1").
            search: Optional substring to narrow the list server-side.

        Returns:
            Dict mapping act code to act name, e.g.
            ``{"18": "NEGOTIABLE INSTRUMENTS ACT, 1881", ...}``.
        """
        await self._init_session()
        form = endpoints.fill_act_type_form(
            state_code=court.state_code,
            court_code=bench_code,
            search_act=search,
        )
        resp = await self._http.post(
            endpoints.FILL_ACT_TYPE_URL,
            data=form,
            headers={"Referer": endpoints.MAIN_PAGE_URL},
        )
        return parse_code_name_list(resp.text)

    async def case_status_by_act(
        self,
        court: Court,
        *,
        act_code: str,
        section: str = "",
        status_filter: str = "Pending",
        bench_code: str = "1",
        year: int | tuple[int, int] | None = None,
        dedupe: bool = True,
    ) -> list[CaseInfo]:
        """Search cases registered under an act, optionally one section.

        This is the court's own record of what a case was filed under \u2014 not
        a text search \u2014 so it finds cases that never name the act in their
        title. For judgments that *mention* an act, use
        :meth:`JudgmentSearchClient.search` with ``act=``.

        The portal returns every match in one response, with no paging and
        no year filter: Delhi's IPC s.302 disposed list is ~16,000 rows and
        6 MB. Pass ``section`` to narrow it; ``year`` is applied client-side
        after the download.

        Args:
            court: Court object.
            act_code: Act code from :meth:`list_acts` for this court.
            section: Section, matched **exactly** ("13" does not find 138).
                Letters, digits and spaces only \u2014 search "138/141" as two
                calls. Empty means every section.
            status_filter: "Pending", "Disposed", or "Both". The portal has
                no "Both", so that makes two requests (two CAPTCHA solves).
            bench_code: Bench code from :meth:`list_benches` (default "1").
            year: Registration year, or an inclusive ``(start, end)`` range.
            dedupe: Collapse the per-party duplicate rows to one per CNR.

        Returns:
            List of CaseInfo. Disposed rows carry ``decision_date``. A few
            rows may carry the trial court's CNR rather than the High
            Court's (seen live on Delhi CRL.M.C. matters: ``DLND…``), so
            don't assume every ``cnr_number`` routes to this court.

        Raises:
            ValueError: On an invalid section or status filter.
        """
        # Before any session or CAPTCHA, as with the advocate search.
        endpoints.validate_section(section)
        statuses = {
            "Pending": ["Pending"],
            "Disposed": ["Disposed"],
            "Both": ["Pending", "Disposed"],
        }.get(status_filter)
        if statuses is None:
            raise ValueError(
                f"status_filter must be 'Pending', 'Disposed' or 'Both', got {status_filter!r}"
            )

        results: list[CaseInfo] = []
        for status in statuses:

            def build_form(captcha: str, status: str = status) -> dict:
                return endpoints.case_status_by_act_form(
                    state_code=court.state_code,
                    court_code=bench_code,
                    act_code=act_code,
                    section=section,
                    status_filter=status,
                    captcha=captcha,
                )

            resp = await self._post_with_captcha_retry(endpoints.SHOW_RECORDS_URL, build_form)
            rows = parse_case_status(resp.text)
            for r in rows:
                r.court_name = court.name
                r.status = status
            results.extend(rows)

        results = filter_by_year(results, year)
        return dedupe_by_cnr(results) if dedupe else results

    async def download_order_pdf(self, pdf_url: str) -> bytes:
        """Download an order/judgment PDF.

        The display_pdf.php endpoint requires a valid Referer header
        and session cookies from the same client that performed the search.

        Args:
            pdf_url: URL from CaseOrder.pdf_url.

        Returns:
            Raw PDF bytes.
        """
        resp = await self._http.get(
            pdf_url,
            headers={
                "Referer": endpoints.MAIN_PAGE_URL,
                "Accept": "application/pdf,*/*",
            },
        )
        content = resp.content
        if content[:4] != b"%PDF":
            raise RuntimeError(
                f"PDF download did not return a valid PDF "
                f"(got {len(content)} bytes; head={content[:64]!r})"
            )
        return content
