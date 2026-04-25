"""Supreme Court of India client.

Targets the live ``www.sci.gov.in`` site (WordPress). The legacy
``main.sci.gov.in`` host has been in long-term maintenance for years —
every endpoint there returns HTTP 503 with a "service is temporarily
unavailable" body — and is no longer the canonical source for SC
judgments. This client now scrapes the homepage's "Latest
Judgements / Orders" feed (50 most recent items, no CAPTCHA) and
downloads PDFs through the portal's ``/sci-get-pdf/?diary_no=...``
endpoint that the in-page viewer iframe uses.

Older judgments / case-number search are gated behind a SimpleCaptcha
form; that flow is not implemented here yet — see
:meth:`SCIClient.search_by_year` and :meth:`SCIClient.search_by_party`
for the deprecation message and the issue link.
"""

from __future__ import annotations

import logging

from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config
from bharat_courts.http import RateLimitedClient
from bharat_courts.models import JudgmentResult
from bharat_courts.sci.parser import parse_recent_judgments

logger = logging.getLogger(__name__)

SCI_BASE = "https://www.sci.gov.in"
SCI_HOME_URL = f"{SCI_BASE}/"
SCI_GET_PDF_URL = f"{SCI_BASE}/sci-get-pdf/"

_PDF_MAGIC = b"%PDF"


class SCIClient:
    """Async client for the Supreme Court of India (``www.sci.gov.in``).

    Usage::

        async with SCIClient() as client:
            recent = await client.list_recent_judgments()
            for j in recent[:3]:
                print(j.judgment_date, j.case_number, j.title)
                pdf = await client.download_pdf(j)  # populates j.pdf_bytes
    """

    def __init__(
        self,
        config: BharatCourtsConfig | None = None,
        http_client: RateLimitedClient | None = None,
    ):
        self._config = config or default_config
        self._http = http_client or RateLimitedClient(self._config)
        self._owns_http = http_client is None

    async def __aenter__(self):
        await self._http.__aenter__()
        return self

    async def __aexit__(self, *args):
        if self._owns_http:
            await self._http.__aexit__(*args)

    async def list_recent_judgments(self, *, limit: int = 50) -> list[JudgmentResult]:
        """Return the homepage's "Latest Judgements / Orders" feed.

        The portal surfaces the 50 most recent items inline on the
        homepage; this method scrapes that list. No CAPTCHA needed.

        Args:
            limit: Maximum number of items to return (the homepage caps
                this at 50). Pass less to truncate.
        """
        resp = await self._http.get(
            SCI_HOME_URL,
            headers={"Referer": SCI_HOME_URL},
        )
        items = parse_recent_judgments(resp.text, base_url=SCI_BASE)
        if limit and limit < len(items):
            items = items[:limit]
        return items

    async def download_pdf(self, judgment: JudgmentResult) -> JudgmentResult:
        """Download the PDF bytes for a judgment.

        Mutates ``judgment`` in-place: sets ``pdf_bytes`` on success.
        ``judgment.pdf_url`` is the ``/sci-get-pdf/?diary_no=...`` URL
        the portal viewer iframe uses.

        Raises:
            RuntimeError: if the response isn't a PDF.
        """
        if not judgment.pdf_url:
            raise RuntimeError(f"No PDF URL on judgment: {judgment.title!r}")

        content = await self._http.get_bytes(
            judgment.pdf_url,
            headers={"Referer": judgment.source_url or SCI_HOME_URL},
        )
        if content[:4] != _PDF_MAGIC:
            raise RuntimeError(
                f"PDF download did not return a valid PDF "
                f"(got {len(content)} bytes; head={content[:64]!r})"
            )
        judgment.pdf_bytes = content
        return judgment

    async def search_by_year(
        self,
        year: int,
        month: int | None = None,
    ) -> list[JudgmentResult]:
        """Date-range search by year/month.

        **Not implemented.** The legacy host (``main.sci.gov.in``) that
        served this form has been permanently 503 for years; the live
        site (``www.sci.gov.in``) only exposes an equivalent through a
        CAPTCHA-protected case-number/diary-number form, which this
        client does not yet wire up. Use
        :meth:`list_recent_judgments` for the most recent items.
        """
        raise NotImplementedError(
            "search_by_year is not supported on the current www.sci.gov.in portal. "
            "Use list_recent_judgments() for recent items, or query by case number "
            "via the portal's /judgements-case-no/ form (CAPTCHA required, "
            "not yet implemented)."
        )

    async def search_by_party(self, party_name: str) -> list[JudgmentResult]:
        """Party-name search.

        **Not implemented.** Same situation as :meth:`search_by_year`.
        """
        raise NotImplementedError(
            "search_by_party is not supported on the current www.sci.gov.in portal. "
            "Use list_recent_judgments() for recent items."
        )
