"""CAPTCHA solving for eCourts portals."""

from bharat_courts.captcha.base import CaptchaSolver
from bharat_courts.captcha.manual import ManualCaptchaSolver

__all__ = ["CaptchaSolver", "ManualCaptchaSolver"]

try:
    from bharat_courts.captcha.onnx import ONNXCaptchaSolver

    __all__ += ["ONNXCaptchaSolver"]
except ImportError:
    pass
