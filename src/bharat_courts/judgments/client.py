"""Judgment search portal client.

Provides async access to ``judgments.ecourts.gov.in`` for searching
High Court / Supreme Court judgments by keyword.

Flow:

1. GET ``/`` — establishes session cookies.
2. GET the CAPTCHA image; solve it with the configured solver.
3. POST ``?p=pdf_search/checkCaptcha`` — validates the CAPTCHA, returns
   an ``app_token`` we must echo back on every subsequent call.
4. POST ``?p=pdf_search/home`` — DataTables AJAX. Returns JSON with a
   ``reportrow.aaData`` list of ``[serial, html_blob]`` rows plus a
   rotated ``app_token``.
5. (Per result) POST ``?p=pdf_search/openpdfcaptcha`` with the row's
   ``path`` to obtain a per-session ``outputfile`` URL, then GET that
   URL for the actual PDF bytes.

The session token rotates on every call; we track it on the instance.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

from bharat_courts.captcha import default_solver
from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config
from bharat_courts.hcservices.parser import CaptchaError
from bharat_courts.http import RateLimitedClient
from bharat_courts.judgments import endpoints
from bharat_courts.judgments.parser import parse_search_response
from bharat_courts.models import JudgmentResult, SearchResult

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF"


class JudgmentSearchClient:
    """Async client for the Judgment Search portal (``judgments.ecourts.gov.in``).

    Usage::

        async with JudgmentSearchClient() as client:
            sr = await client.search("section 498A")
            print(sr.total_count, len(sr.items))
            for j in sr.items:
                print(j.case_number, j.court_name, j.judgment_date)
                pdf = await client.download_pdf(j)  # populates j.pdf_bytes
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
        self._app_token: str = ""

    async def __aenter__(self):
        await self._http.__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._owns_http:
            await self._http.__aexit__(*args)

    # -- session / CAPTCHA ----------------------------------------------------

    def _update_token_from_response(self, data: dict) -> None:
        token = data.get("app_token", "")
        if token:
            self._app_token = token

    async def _init_session(self) -> None:
        await self._http.get(endpoints.MAIN_PAGE_URL)

    async def _solve_captcha(self) -> str:
        resp = await self._http.get(endpoints.CAPTCHA_IMAGE_URL)
        return await self._captcha_solver.solve(resp.content)

    async def _validate_captcha(self, captcha: str, search_text: str) -> bool:
        body = endpoints.check_captcha_form(captcha=captcha, search_text=search_text)
        resp = await self._http.post(
            endpoints.CHECK_CAPTCHA_URL,
            content=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
        )

        # Length-error envelope: "<msg><br/>#####<hex token>"
        text = resp.text
        if "#####" in text:
            parts = text.split("#####", 1)
            msg = parts[0].strip()
            token = parts[1].strip() if len(parts) > 1 else ""
            if token and 32 <= len(token) <= 128 and all(c in "0123456789abcdef" for c in token):
                self._app_token = token
            logger.warning("CAPTCHA validate non-JSON response: %s", msg[:200])
            return False

        try:
            data = resp.json()
        except Exception:
            logger.error("CAPTCHA check returned non-JSON: %s", text[:200])
            return False

        self._update_token_from_response(data)
        if data.get("captcha_status") == "Y":
            return True
        logger.warning("CAPTCHA failed: %s", data.get("errormsg", "Unknown"))
        return False

    async def _authenticate(self, search_text: str, *, max_captcha_attempts: int = 5) -> str | None:
        for attempt in range(max_captcha_attempts):
            if attempt > 0:
                logger.info("CAPTCHA retry %d/%d — new session", attempt + 1, max_captcha_attempts)
            await self._init_session()
            captcha_text = await self._solve_captcha()
            if not captcha_text:
                logger.warning("Empty CAPTCHA response, attempt %d", attempt + 1)
                continue
            if await self._validate_captcha(captcha_text, search_text):
                return captcha_text
        logger.error("Failed to solve CAPTCHA after %d attempts", max_captcha_attempts)
        return None

    # -- search ---------------------------------------------------------------

    async def _post_search(
        self,
        *,
        search_text: str,
        captcha_text: str,
        search_opt: str,
        court_type: str,
        page: int,
        page_size: int,
    ) -> dict:
        body = endpoints.search_results_form(
            search_text=search_text,
            captcha=captcha_text,
            app_token=self._app_token,
            search_opt=search_opt,
            court_type=court_type,
            page=page,
            page_size=page_size,
        )
        resp = await self._http.post(
            endpoints.SEARCH_RESULTS_URL,
            content=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        # Portal occasionally prefixes the JSON with whitespace / blank lines.
        text = resp.text.lstrip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("Search response was not JSON: %s", text[:200])
            raise RuntimeError("Search response was not JSON") from e
        self._update_token_from_response(data)
        return data

    async def search(
        self,
        search_text: str,
        *,
        page: int = 1,
        page_size: int = 10,
        search_opt: str = "PHRASE",
        court_type: str = "2",
        max_captcha_attempts: int = 5,
    ) -> SearchResult:
        """Search for judgments by keyword.

        Args:
            search_text: Keywords / phrase to search for.
            page: 1-indexed page number.
            page_size: Rows per page (portal supports 10/25/50/100/1000).
            search_opt: ``"PHRASE"``, ``"ANY"``, or ``"ALL"``.
            court_type: ``"2"`` for High Courts, ``"3"`` for SCR.
            max_captcha_attempts: Max CAPTCHA solve retries before giving up.

        Returns:
            ``SearchResult`` of :class:`JudgmentResult` items.

        Raises:
            CaptchaError: if the CAPTCHA solver couldn't produce a valid
                solution within ``max_captcha_attempts`` tries. Empty
                results are now distinguishable from "we gave up": empty
                means the portal returned zero rows.
        """
        captcha_text = await self._authenticate(
            search_text, max_captcha_attempts=max_captcha_attempts
        )
        if captcha_text is None:
            raise CaptchaError(f"Failed to solve CAPTCHA after {max_captcha_attempts} attempts")

        data = await self._post_search(
            search_text=search_text,
            captcha_text=captcha_text,
            search_opt=search_opt,
            court_type=court_type,
            page=page,
            page_size=page_size,
        )
        return parse_search_response(data, page=page, page_size=page_size)

    async def search_all(
        self,
        search_text: str,
        *,
        page_size: int = 25,
        search_opt: str = "PHRASE",
        court_type: str = "2",
        max_captcha_attempts: int = 5,
    ) -> AsyncIterator[SearchResult]:
        """Iterate through every page of results, yielding one SearchResult
        per page. Re-authenticates if the session token expires mid-walk."""
        captcha_text = await self._authenticate(
            search_text, max_captcha_attempts=max_captcha_attempts
        )
        if captcha_text is None:
            raise CaptchaError(f"Failed to solve CAPTCHA after {max_captcha_attempts} attempts")

        page = 1
        while True:
            try:
                data = await self._post_search(
                    search_text=search_text,
                    captcha_text=captcha_text,
                    search_opt=search_opt,
                    court_type=court_type,
                    page=page,
                    page_size=page_size,
                )
            except RuntimeError:
                logger.info("Session likely expired at page %d, re-auth", page)
                captcha_text = await self._authenticate(
                    search_text, max_captcha_attempts=max_captcha_attempts
                )
                if captcha_text is None:
                    raise CaptchaError(
                        f"Failed to solve CAPTCHA after {max_captcha_attempts} attempts"
                    ) from None
                continue

            result = parse_search_response(data, page=page, page_size=page_size)
            yield result
            if not result.has_next or not result.items:
                break
            page += 1

    # -- PDF download ---------------------------------------------------------

    async def _resolve_pdf_url(
        self,
        path: str,
        *,
        court_type: str = "2",
        val: str = "0",
        citation_year: str = "",
    ) -> str:
        """Exchange a row's ``open_pdf`` path for a downloadable URL via
        ``?p=pdf_search/openpdfcaptcha``. The path's ``#page=...`` fragment
        is stripped before sending — the controller returns 405 otherwise.

        ``val`` is the row index (``open_pdf(val, ...)`` from the row
        HTML). The portal uses it as a session-scoped row key — sending
        ``val="0"`` for every call makes it serve the first row's PDF
        regardless of the path you pass. The caller MUST supply the
        per-row val from ``judgment.metadata["pdf_val"]``.
        """
        body = endpoints.open_pdf_captcha_form(
            path=path,
            app_token=self._app_token,
            court_type=court_type,
            val=val,
            citation_year=citation_year,
        )
        resp = await self._http.post(
            endpoints.OPEN_PDF_CAPTCHA_URL,
            content=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
            },
        )
        text = resp.text.lstrip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"openpdfcaptcha returned non-JSON: {text[:200]!r}") from e
        self._update_token_from_response(data)
        outputfile = data.get("outputfile") or ""
        if not outputfile:
            msg = data.get("message") or "no outputfile in response"
            raise RuntimeError(f"openpdfcaptcha did not return a PDF URL: {msg}")
        if outputfile.startswith("http"):
            return outputfile
        return f"{endpoints.SITE_ROOT}{outputfile}"

    async def download_pdf(
        self,
        judgment: JudgmentResult,
        *,
        court_type: str = "2",
    ) -> JudgmentResult:
        """Download the PDF for a judgment result.

        Mutates ``judgment`` in-place: sets ``pdf_bytes`` if the download
        succeeds. The ``judgment.pdf_url`` slot stores the row's relative
        ``path`` (from ``open_pdf(...)``), not a directly-fetchable URL —
        we resolve it through the portal's ``openpdfcaptcha`` endpoint
        before downloading.

        Raises:
            RuntimeError: if the download didn't return PDF bytes.
        """
        if not judgment.pdf_url:
            raise RuntimeError(f"No PDF path on judgment: {judgment.title!r}")

        # If pdf_url already looks resolved (full https URL), trust it.
        if judgment.pdf_url.startswith("http"):
            url = judgment.pdf_url
        else:
            # `val` is the row's open_pdf(VAL, ...) index. The portal
            # uses it as a session-scoped key when generating the temp
            # outputfile; without it (or with the same val for every
            # row) the portal serves the first row's PDF for every
            # subsequent call.
            val = (judgment.metadata or {}).get("pdf_val", "0")
            citation_year = (judgment.metadata or {}).get("pdf_citation_year", "")
            url = await self._resolve_pdf_url(
                judgment.pdf_url,
                court_type=court_type,
                val=val,
                citation_year=citation_year,
            )

        content = await self._http.get_bytes(
            url,
            headers={"Referer": endpoints.MAIN_PAGE_URL},
        )
        if content[:4] != _PDF_MAGIC:
            raise RuntimeError(
                f"PDF download did not return a valid PDF "
                f"(got {len(content)} bytes; head={content[:64]!r})"
            )
        judgment.pdf_bytes = content
        return judgment

    async def download_pdfs(
        self,
        judgments: list[JudgmentResult],
        *,
        court_type: str = "2",
        stop_on_error: bool = False,
    ) -> list[JudgmentResult]:
        """Download PDFs for multiple judgments. Skips ones that already
        have ``pdf_bytes`` set. Errors are logged unless ``stop_on_error``."""
        for j in judgments:
            if j.pdf_bytes is not None or not j.pdf_url:
                continue
            try:
                await self.download_pdf(j, court_type=court_type)
            except Exception as e:
                logger.warning("PDF download failed for %r: %s", j.case_number or j.title, e)
                if stop_on_error:
                    raise
        return judgments
