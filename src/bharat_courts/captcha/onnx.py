"""ONNX-based CAPTCHA solver for eCourts Securimage CAPTCHAs.

Uses an ONNX model from HuggingFace (captchabreaker) for inference.
Lighter alternative to ddddocr — uses standard onnxruntime + Pillow.

Install: pip install bharat-courts[onnx]
"""

from __future__ import annotations

import logging
import string
from pathlib import Path

from bharat_courts.captcha.base import CaptchaSolver

logger = logging.getLogger(__name__)

try:
    import numpy as np
    import onnxruntime as ort

    HAS_ONNX = True
except ImportError:
    HAS_ONNX = False

try:
    import io

    from PIL import Image

    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

# CTC blank token index (conventionally 0)
_CTC_BLANK = 0

# Character set: digits + lowercase + uppercase (matching captchabreaker model)
_CHARSET = string.digits + string.ascii_lowercase + string.ascii_uppercase

# Default model from HuggingFace
_DEFAULT_MODEL_REPO = "https://huggingface.co/thelou1s/captchabreaker/resolve/main/model.onnx"
_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "bharat-courts"

# Expected CAPTCHA length
_EXPECTED_LENGTH = 6

# Preprocessing constants
_TARGET_WIDTH = 200
_TARGET_HEIGHT = 70


def _ctc_greedy_decode(logits: list[list[float]]) -> str:
    """Greedy CTC decoding: pick best class per timestep, collapse repeats, remove blanks."""
    prev = _CTC_BLANK
    chars: list[str] = []
    for timestep in logits:
        best = max(range(len(timestep)), key=lambda i: timestep[i])
        if best != _CTC_BLANK and best != prev:
            idx = best - 1  # offset by 1 since blank is at index 0
            if 0 <= idx < len(_CHARSET):
                chars.append(_CHARSET[idx])
        prev = best
    return "".join(chars)


class ONNXCaptchaSolver(CaptchaSolver):
    """CAPTCHA solver using ONNX Runtime for Securimage CAPTCHAs.

    Requires the ``onnx`` extra: ``pip install bharat-courts[onnx]``

    Uses a pre-trained ONNX model (captchabreaker from HuggingFace).
    The model is lazily downloaded on first use to ``~/.cache/bharat-courts/``.

    Args:
        model_path: Optional path to a custom ONNX model file.
            If not provided, downloads the default captchabreaker model.
    """

    def __init__(self, model_path: str | Path | None = None):
        if not HAS_ONNX:
            raise ImportError(
                "onnxruntime is required for ONNX CAPTCHA solving. "
                "Install with: pip install bharat-courts[onnx]"
            )
        if not HAS_PILLOW:
            raise ImportError(
                "Pillow is required for ONNX CAPTCHA solving. "
                "Install with: pip install bharat-courts[onnx]"
            )
        self._model_path = Path(model_path) if model_path else None
        self._session: ort.InferenceSession | None = None

    def _ensure_model(self) -> Path:
        """Ensure the ONNX model is available, downloading if needed."""
        if self._model_path and self._model_path.exists():
            return self._model_path

        cache_dir = _DEFAULT_CACHE_DIR
        cache_dir.mkdir(parents=True, exist_ok=True)
        model_file = cache_dir / "captcha_model.onnx"

        if model_file.exists():
            return model_file

        logger.info("Downloading CAPTCHA ONNX model to %s", model_file)
        import urllib.request

        urllib.request.urlretrieve(_DEFAULT_MODEL_REPO, model_file)
        logger.info("Model downloaded successfully")
        return model_file

    def _get_session(self) -> ort.InferenceSession:
        """Lazily create the ONNX inference session."""
        if self._session is None:
            model_path = self._ensure_model()
            self._session = ort.InferenceSession(
                str(model_path),
                providers=["CPUExecutionProvider"],
            )
        return self._session

    def _preprocess(self, image_bytes: bytes) -> np.ndarray:
        """Preprocess CAPTCHA image for ONNX model input.

        Resizes to target dimensions, converts to grayscale, normalizes to [0, 1].
        Returns array of shape (1, 1, height, width) — NCHW format.
        """
        img = Image.open(io.BytesIO(image_bytes))
        img = img.resize((_TARGET_WIDTH, _TARGET_HEIGHT), Image.Resampling.BILINEAR)
        img = img.convert("L")  # grayscale

        arr = np.array(img, dtype=np.float32) / 255.0
        # NCHW: batch=1, channels=1, height, width
        return arr.reshape(1, 1, _TARGET_HEIGHT, _TARGET_WIDTH)

    async def solve(self, image_bytes: bytes) -> str:
        """Recognize CAPTCHA text from image bytes using ONNX model.

        Returns the recognized text if it's exactly 6 characters,
        otherwise returns empty string to trigger a client retry.
        """
        session = self._get_session()
        input_tensor = self._preprocess(image_bytes)

        input_name = session.get_inputs()[0].name
        outputs = session.run(None, {input_name: input_tensor})

        # outputs[0] shape: (batch, timesteps, num_classes)
        logits = outputs[0][0].tolist()
        text = _ctc_greedy_decode(logits)

        if len(text) != _EXPECTED_LENGTH:
            logger.warning(
                "ONNX CAPTCHA decoded %d chars (expected %d): %r",
                len(text),
                _EXPECTED_LENGTH,
                text,
            )
            return ""

        return text
