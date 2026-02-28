"""Manual CAPTCHA solver — prompts user or invokes a callback."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path

from bharat_courts.captcha.base import CaptchaSolver


class ManualCaptchaSolver(CaptchaSolver):
    """Solver that asks a human to read the CAPTCHA.

    By default, saves the image to a temp file and prompts on stdin.
    Pass a custom callback for GUI or web-based workflows.
    """

    def __init__(self, callback: Callable[[bytes], str | Awaitable[str]] | None = None):
        self._callback = callback

    async def solve(self, image_bytes: bytes) -> str:
        if self._callback is not None:
            result = self._callback(image_bytes)
            if hasattr(result, "__await__"):
                return await result
            return result

        # Default: save to temp file and prompt on stdin
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(image_bytes)
            tmp_path = Path(f.name)

        print(f"CAPTCHA image saved to: {tmp_path}", file=sys.stderr)
        print("Enter CAPTCHA text: ", end="", file=sys.stderr, flush=True)
        text = input().strip()
        tmp_path.unlink(missing_ok=True)
        return text
