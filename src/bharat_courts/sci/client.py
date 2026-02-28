"""Supreme Court of India client.

Provides async access to main.sci.gov.in for judgment search and download.
"""

from __future__ import annotations

import logging

from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config
from bharat_courts.http import RateLimitedClient
from bharat_courts.models import JudgmentResult
from bharat_courts.sci.parser import parse_judgment_list

logger = logging.getLogger(__name__)

SCI_BASE = "https://main.sci.gov.in"
SCI_JUDGMENTS_URL = f"{SCI_BASE}/judgments"


class SCIClient:
    """Async client for Supreme Court of India (main.sci.gov.in).

    Usage::

        async with SCIClient() as client:
            judgments = await client.search_by_year(2024)
            for j in judgments:
                print(j.title, j.judgment_date)
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

    async def search_by_year(
        self,
        year: int,
        month: int | None = None,
    ) -> list[JudgmentResult]:
        """Search SC judgments by year and optional month.

        Args:
            year: Year to search.
            month: Optional month (1-12).

        Returns:
            List of JudgmentResult objects.
        """
        if month:
            from_date = f"01-{month:02d}-{year}"
            to_date = f"28-{month:02d}-{year}"
        else:
            from_date = f"01-01-{year}"
            to_date = f"31-12-{year}"

        form_data = {
            "JBJfrom": from_date,
            "JBJto": to_date,
            "joession": "",
        }

        resp = await self._http.post(SCI_JUDGMENTS_URL, data=form_data)
        return parse_judgment_list(resp.text, base_url=SCI_BASE)

    async def search_by_party(self, party_name: str) -> list[JudgmentResult]:
        """Search SC judgments by party name.

        Args:
            party_name: Name of petitioner or respondent.

        Returns:
            List of JudgmentResult objects.
        """
        form_data = {
            "JBJfrom": "",
            "JBJto": "",
            "joession": "",
            "party_name": party_name,
        }

        resp = await self._http.post(SCI_JUDGMENTS_URL, data=form_data)
        return parse_judgment_list(resp.text, base_url=SCI_BASE)

    async def download_pdf(self, judgment: JudgmentResult) -> JudgmentResult:
        """Download the PDF for a judgment.

        Modifies the judgment in-place, setting pdf_bytes.
        """
        if not judgment.pdf_url:
            logger.warning("No PDF URL for judgment: %s", judgment.title)
            return judgment

        judgment.pdf_bytes = await self._http.get_bytes(judgment.pdf_url)
        return judgment
