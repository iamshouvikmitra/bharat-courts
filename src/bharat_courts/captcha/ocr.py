"""OCR-based CAPTCHA solver using ddddocr.

eCourts uses Securimage CAPTCHAs — distorted alphanumeric text on a noisy
background. ddddocr handles these well out of the box.

Fallback: if ddddocr is not installed, uses Pillow preprocessing and
returns empty string (for manual fallback).

Install: pip install bharat-courts[ocr]
"""

from __future__ import annotations

import logging

from bharat_courts.captcha.base import CaptchaSolver

logger = logging.getLogger(__name__)

_EXPECTED_LENGTH = 6

try:
    import ddddocr

    HAS_DDDDOCR = True
except ImportError:
    HAS_DDDDOCR = False

try:
    import io

    from PIL import Image, ImageFilter

    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False


class OCRCaptchaSolver(CaptchaSolver):
    """CAPTCHA solver using ddddocr for Securimage CAPTCHAs.

    Requires the `ocr` extra: ``pip install bharat-courts[ocr]``

    Uses ddddocr (deep-learning CAPTCHA recognition) which works well
    with eCourts' Securimage CAPTCHAs. Optionally applies Pillow
    preprocessing to improve accuracy on noisy images.
    """

    def __init__(self, preprocess: bool = False, threshold: int = 128):
        """Initialize the OCR solver.

        Args:
            preprocess: Apply Pillow preprocessing before OCR.
            threshold: Binarization threshold (0-255) for preprocessing.
        """
        if not HAS_DDDDOCR:
            raise ImportError(
                "ddddocr is required for OCR CAPTCHA solving. "
                "Install with: pip install bharat-courts[ocr]"
            )
        self._ocr = ddddocr.DdddOcr(show_ad=False)
        self._preprocess = preprocess and HAS_PILLOW
        self._threshold = threshold

    async def solve(self, image_bytes: bytes) -> str:
        """Recognize CAPTCHA text from image bytes.

        Returns an empty string if the OCR output isn't a valid 6-char
        alphanumeric — eCourts portals reject anything else with a
        length-validation error, so we short-circuit and signal upstream
        callers to skip this attempt.
        """
        if self._preprocess:
            image_bytes = self._preprocess_image(image_bytes)
        result = self._ocr.classification(image_bytes)
        result = result.strip() if isinstance(result, str) else ""
        if len(result) != _EXPECTED_LENGTH or not result.isalnum():
            logger.warning(
                "OCR CAPTCHA decoded %d chars (expected %d): %r",
                len(result),
                _EXPECTED_LENGTH,
                result,
            )
            return ""
        return result

    def _preprocess_image(self, image_bytes: bytes) -> bytes:
        """Apply basic image preprocessing to improve OCR accuracy."""
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("L")
        img = img.point(lambda x: 255 if x > self._threshold else 0, "1")
        img = img.filter(ImageFilter.MedianFilter(size=3))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
