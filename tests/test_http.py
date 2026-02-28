"""Tests for the rate-limited HTTP client."""

import pytest
import respx
from httpx import Response

from bharat_courts.config import BharatCourtsConfig
from bharat_courts.http import RateLimitedClient


@pytest.fixture
def fast_config():
    """Config with no delay for fast tests."""
    return BharatCourtsConfig(request_delay=0, timeout=5, max_retries=2)


@pytest.mark.asyncio
async def test_get_success(fast_config):
    with respx.mock:
        respx.get("https://example.com/test").mock(return_value=Response(200, text="ok"))

        async with RateLimitedClient(fast_config) as client:
            resp = await client.get("https://example.com/test")
            assert resp.status_code == 200
            assert resp.text == "ok"


@pytest.mark.asyncio
async def test_post_success(fast_config):
    with respx.mock:
        respx.post("https://example.com/submit").mock(return_value=Response(200, text="done"))

        async with RateLimitedClient(fast_config) as client:
            resp = await client.post("https://example.com/submit", data={"key": "val"})
            assert resp.text == "done"


@pytest.mark.asyncio
async def test_get_bytes(fast_config):
    with respx.mock:
        respx.get("https://example.com/file.pdf").mock(
            return_value=Response(200, content=b"PDF_CONTENT")
        )

        async with RateLimitedClient(fast_config) as client:
            data = await client.get_bytes("https://example.com/file.pdf")
            assert data == b"PDF_CONTENT"


@pytest.mark.asyncio
async def test_get_text(fast_config):
    with respx.mock:
        respx.get("https://example.com/page").mock(
            return_value=Response(200, text="<html>hello</html>")
        )

        async with RateLimitedClient(fast_config) as client:
            text = await client.get_text("https://example.com/page")
            assert "hello" in text


@pytest.mark.asyncio
async def test_retry_on_error(fast_config):
    with respx.mock:
        route = respx.get("https://example.com/flaky")
        route.side_effect = [
            Response(500),
            Response(200, text="recovered"),
        ]

        async with RateLimitedClient(fast_config) as client:
            resp = await client.get("https://example.com/flaky")
            assert resp.text == "recovered"


@pytest.mark.asyncio
async def test_max_retries_exceeded(fast_config):
    with respx.mock:
        respx.get("https://example.com/down").mock(return_value=Response(500))

        async with RateLimitedClient(fast_config) as client:
            with pytest.raises(Exception):
                await client.get("https://example.com/down")


@pytest.mark.asyncio
async def test_context_manager(fast_config):
    client = RateLimitedClient(fast_config)
    async with client:
        assert client._client is not None
    assert client._client is None
