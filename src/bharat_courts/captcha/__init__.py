"""CAPTCHA solving for eCourts portals."""

import logging

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.captcha.manual import ManualCaptchaSolver

__all__ = ["CaptchaSolver", "ManualCaptchaSolver", "default_solver"]

try:
    from bharat_courts.captcha.onnx import ONNXCaptchaSolver

    __all__ += ["ONNXCaptchaSolver"]
except ImportError:
    pass

_logger = logging.getLogger(__name__)


def default_solver() -> CaptchaSolver:
    """Return the best available CAPTCHA solver.

    Prefers OCRCaptchaSolver (ddddocr) since it bundles its own model.
    Falls back to ManualCaptchaSolver if ddddocr is not installed.
    """
    try:
        from bharat_courts.captcha.ocr import OCRCaptchaSolver

        return OCRCaptchaSolver()
    except ImportError:
        pass

    _logger.warning(
        "No automatic CAPTCHA solver available. "
        "Install one with: pip install bharat-courts[ocr]  — "
        "Falling back to manual (stdin) solver."
    )
    return ManualCaptchaSolver()
