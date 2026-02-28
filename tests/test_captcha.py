"""Tests for CAPTCHA solvers."""

import pytest

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.captcha.manual import ManualCaptchaSolver


class MockCaptchaSolver(CaptchaSolver):
    async def solve(self, image_bytes: bytes) -> str:
        return "ABC123"


@pytest.mark.asyncio
async def test_mock_solver():
    solver = MockCaptchaSolver()
    result = await solver.solve(b"fake_image_data")
    assert result == "ABC123"


@pytest.mark.asyncio
async def test_manual_solver_with_sync_callback():
    def callback(image_bytes: bytes) -> str:
        assert image_bytes == b"test_image"
        return "SOLVED"

    solver = ManualCaptchaSolver(callback=callback)
    result = await solver.solve(b"test_image")
    assert result == "SOLVED"


@pytest.mark.asyncio
async def test_manual_solver_with_async_callback():
    async def callback(image_bytes: bytes) -> str:
        return "ASYNC_SOLVED"

    solver = ManualCaptchaSolver(callback=callback)
    result = await solver.solve(b"test_image")
    assert result == "ASYNC_SOLVED"
