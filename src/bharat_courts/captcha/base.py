"""Abstract base for CAPTCHA solvers."""

from abc import ABC, abstractmethod


class CaptchaSolver(ABC):
    """Base class for solving eCourts Securimage CAPTCHAs."""

    @abstractmethod
    async def solve(self, image_bytes: bytes) -> str:
        """Given raw CAPTCHA image bytes, return the solved text.

        Args:
            image_bytes: PNG/JPEG bytes of the CAPTCHA image.

        Returns:
            The CAPTCHA text as a string.
        """
        ...
