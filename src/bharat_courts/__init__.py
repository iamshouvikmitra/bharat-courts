"""bharat-courts — Async Python client for Indian court data."""

from bharat_courts._version import __version__
from bharat_courts.calcuttahc.client import CalcuttaHCClient
from bharat_courts.captcha import CaptchaSolver, ManualCaptchaSolver, default_solver
from bharat_courts.config import BharatCourtsConfig, config
from bharat_courts.courts import (
    ALL_COURTS,
    SUPREME_COURT,
    get_court,
    get_court_by_name,
    get_court_by_state_code,
    infer_court_from_cnr,
    list_all_courts,
    list_high_courts,
)
from bharat_courts.districtcourts.client import DistrictCourtClient
from bharat_courts.hcservices.client import HCServicesClient
from bharat_courts.hcservices.parser import CaptchaError
from bharat_courts.http import RateLimitedClient
from bharat_courts.judgments.client import JudgmentSearchClient
from bharat_courts.models import (
    CaseInfo,
    CaseOrder,
    CauseListEntry,
    CauseListPDF,
    Court,
    CourtType,
    Judgment,
    JudgmentResult,
    SearchResult,
)
from bharat_courts.sci.client import SCIClient

__all__ = [
    "__version__",
    "ALL_COURTS",
    "BharatCourtsConfig",
    "CalcuttaHCClient",
    "CaptchaError",
    "CaptchaSolver",
    "DistrictCourtClient",
    "CaseInfo",
    "CaseOrder",
    "CauseListEntry",
    "CauseListPDF",
    "config",
    "Court",
    "CourtType",
    "default_solver",
    "get_court",
    "get_court_by_name",
    "get_court_by_state_code",
    "infer_court_from_cnr",
    "HCServicesClient",
    "Judgment",
    "JudgmentResult",
    "JudgmentSearchClient",
    "list_all_courts",
    "list_high_courts",
    "ManualCaptchaSolver",
    "RateLimitedClient",
    "SCIClient",
    "SearchResult",
    "SUPREME_COURT",
]

try:
    from bharat_courts.captcha.ocr import OCRCaptchaSolver  # noqa: F401

    __all__ += ["OCRCaptchaSolver"]
except ImportError:
    pass

try:
    from bharat_courts.captcha.onnx import ONNXCaptchaSolver  # noqa: F401

    __all__ += ["ONNXCaptchaSolver"]
except ImportError:
    pass

try:
    from bharat_courts.archive.client import ArchiveClient  # noqa: F401

    __all__ += ["ArchiveClient"]
except ImportError:
    pass
