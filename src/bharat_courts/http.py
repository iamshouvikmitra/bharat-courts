"""Rate-limited async HTTP client with retry logic."""

import asyncio
import logging

import httpx

from bharat_courts.config import BharatCourtsConfig
from bharat_courts.config import config as default_config

logger = logging.getLogger(__name__)


class RateLimitedClient:
    """Async HTTP client with rate limiting, retries, and SSL bypass.

    Government websites often have expired/invalid SSL certs, so verification
    is disabled by default.
    """

    def __init__(self, config: BharatCourtsConfig | None = None):
        self._config = config or default_config
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._config.timeout,
                headers={
                    "User-Agent": self._config.user_agent,
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Accept-Language": "en-US,en;q=0.9",
                    "X-Requested-With": "XMLHttpRequest",
                },
                follow_redirects=True,
                verify=False,
            )
        return self._client

    async def __aenter__(self):
        self._ensure_client()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """GET with rate limiting and retry."""
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        """POST with rate limiting and retry."""
        return await self._request("POST", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Execute request with rate limiting and exponential backoff retry."""
        client = self._ensure_client()
        await asyncio.sleep(self._config.request_delay)

        last_error: Exception | None = None
        for attempt in range(self._config.max_retries):
            try:
                resp = await client.request(method, url, **kwargs)
                resp.raise_for_status()
                return resp
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadTimeout) as e:
                last_error = e
                if attempt == self._config.max_retries - 1:
                    raise
                wait = (attempt + 1) * 2
                logger.warning(
                    "Retry %d/%d for %s %s: %s. Waiting %ds.",
                    attempt + 1,
                    self._config.max_retries,
                    method,
                    url,
                    e,
                    wait,
                )
                await asyncio.sleep(wait)

        msg = f"Request failed after {self._config.max_retries} retries"
        raise RuntimeError(msg) from last_error

    async def get_bytes(self, url: str, **kwargs) -> bytes:
        """GET and return raw bytes (for PDF downloads)."""
        resp = await self.get(url, **kwargs)
        return resp.content

    async def get_text(self, url: str, **kwargs) -> str:
        """GET and return decoded text."""
        resp = await self.get(url, **kwargs)
        return resp.text
