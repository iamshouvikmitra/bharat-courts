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


def test_default_solver_returns_captcha_solver():
    """default_solver() returns a CaptchaSolver regardless of installed packages."""
    from bharat_courts.captcha import default_solver

    solver = default_solver()
    assert isinstance(solver, CaptchaSolver)


def test_default_solver_prefers_ocr(monkeypatch):
    """When OCRCaptchaSolver is importable, default_solver() returns it."""
    from unittest.mock import MagicMock

    fake_ocr_module = MagicMock()
    fake_ocr_class = type("OCRCaptchaSolver", (CaptchaSolver,), {
        "solve": lambda self, img: "mocked",
    })
    fake_ocr_module.OCRCaptchaSolver = fake_ocr_class

    import sys

    monkeypatch.setitem(sys.modules, "bharat_courts.captcha.ocr", fake_ocr_module)
    from bharat_courts.captcha import default_solver

    solver = default_solver()
    assert type(solver).__name__ == "OCRCaptchaSolver"


def test_default_solver_falls_back_to_manual(monkeypatch):
    """When OCRCaptchaSolver import fails, default_solver() returns ManualCaptchaSolver."""
    import builtins

    real_import = builtins.__import__

    def _blocked_import(name, *args, **kwargs):
        if name == "bharat_courts.captcha.ocr":
            raise ImportError("no ocr")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked_import)
    from bharat_courts.captcha import default_solver

    solver = default_solver()
    assert isinstance(solver, ManualCaptchaSolver)
