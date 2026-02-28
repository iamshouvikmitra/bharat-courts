"""bharat-courts — Async Python client for Indian court data."""

from bharat_courts._version import __version__
from bharat_courts.config import BharatCourtsConfig, config
from bharat_courts.courts import (
    ALL_COURTS,
    SUPREME_COURT,
    get_court,
    get_court_by_name,
    list_all_courts,
    list_high_courts,
)
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
    JudgmentResult,
    SearchResult,
)

__all__ = [
    "__version__",
    "ALL_COURTS",
    "BharatCourtsConfig",
    "CaptchaError",
    "CaseInfo",
    "CaseOrder",
    "CauseListEntry",
    "CauseListPDF",
    "config",
    "Court",
    "CourtType",
    "get_court",
    "get_court_by_name",
    "HCServicesClient",
    "JudgmentResult",
    "JudgmentSearchClient",
    "list_all_courts",
    "list_high_courts",
    "RateLimitedClient",
    "SearchResult",
    "SUPREME_COURT",
]
