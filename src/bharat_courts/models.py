"""Data models for bharat-courts.

All models are dataclasses with built-in JSON serialization via `to_dict()`
and `to_json()`. Date fields serialize to ISO 8601 strings. Enum fields
serialize to their string values. Binary fields (pdf_bytes) are excluded
from serialization by default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import date
from enum import Enum
from typing import Any


def _serialize_value(v: Any) -> Any:
    """Convert non-JSON-serializable values."""
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, bytes):
        return None
    if isinstance(v, list):
        return [_serialize_value(i) for i in v]
    if isinstance(v, dict):
        return {k: _serialize_value(val) for k, val in v.items()}
    if hasattr(v, "to_dict") and callable(v.to_dict):
        # Recurse into nested serializable models (e.g. Judgment.court → Court).
        return v.to_dict()
    return v


class _Serializable:
    """Mixin that adds to_dict() and to_json() to dataclasses."""

    def to_dict(self, *, exclude_none: bool = False) -> dict[str, Any]:
        """Convert to a plain dict with JSON-safe values.

        Args:
            exclude_none: If True, omit fields with None values.
        """
        result = {}
        for f in fields(self):  # type: ignore[arg-type]
            val = getattr(self, f.name)
            serialized = _serialize_value(val)
            if exclude_none and serialized is None:
                continue
            result[f.name] = serialized
        return result

    def to_json(self, *, indent: int | None = None, exclude_none: bool = False) -> str:
        """Serialize to a JSON string.

        Args:
            indent: JSON indentation level (None for compact).
            exclude_none: If True, omit fields with None values.
        """
        return json.dumps(self.to_dict(exclude_none=exclude_none), indent=indent)


class CourtType(str, Enum):
    SUPREME_COURT = "supreme_court"
    HIGH_COURT = "high_court"
    DISTRICT_COURT = "district_court"
    TRIBUNAL = "tribunal"


@dataclass(frozen=True)
class Court(_Serializable):
    """An Indian court with its eCourts identifiers."""

    name: str
    code: str  # eCourts court complex code
    state_code: str  # eCourts state code
    court_type: CourtType
    bench: str | None = None  # e.g. "Lucknow Bench" for Allahabad HC
    judgment_code: str = ""  # judgments.ecourts.gov.in court code

    @property
    def slug(self) -> str:
        return self.code.lower().replace(" ", "-")

    @property
    def judgment_compound_code(self) -> str:
        """Compound code for judgments portal: ``{judgment_code}~{state_code}``."""
        if not self.judgment_code:
            return ""
        return f"{self.judgment_code}~{self.state_code}"


@dataclass
class CaseInfo(_Serializable):
    """Basic case metadata from a search result."""

    case_number: str  # e.g. "3/2024"
    case_type: str  # Case type label (e.g. "W.P.(C)")
    cnr_number: str = ""  # Court Number Record, e.g. "DLHC010582482024"
    filing_number: str = ""
    registration_number: str = ""
    registration_date: date | None = None
    petitioner: str = ""
    respondent: str = ""
    status: str = ""  # "Pending" | "Disposed"
    court_name: str = ""
    judges: list[str] = field(default_factory=list)
    next_hearing_date: date | None = None


@dataclass
class CaseOrder(_Serializable):
    """A single order/judgment attached to a case."""

    order_date: date
    order_type: str  # "Judgment" | "Order" | "Interim Order"
    judge: str = ""
    pdf_url: str = ""
    pdf_bytes: bytes | None = None
    order_text: str = ""
    neutral_citation: str = ""


@dataclass
class JudgmentResult(_Serializable):
    """A judgment from the judgment search portal."""

    title: str
    court_name: str
    case_number: str = ""
    judgment_date: date | None = None
    judges: list[str] = field(default_factory=list)
    pdf_url: str = ""
    pdf_bytes: bytes | None = None
    citation: str = ""
    bench_type: str = ""  # "Division Bench" | "Single Bench" | "Full Bench"
    source_url: str = ""
    source_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class Judgment(_Serializable):
    """A delivered judgment, source-agnostic.

    Populated by the archive client (parquet metadata) and, in later phases,
    by the live judgment-search clients via a federated facade. Fields that
    don't apply to a given source are left ``None`` / empty.
    """

    # Identity — CNR is the join key with the live SDK.
    cnr: str | None = None
    case_id: str | None = None  # e.g. "1950 INSC 25" (SCI only)
    title: str | None = None

    # Bench
    court: Court | None = None  # normalized bharat-courts Court
    # Original string from the archive parquet (SCI only — for HC the resolved
    # ``court`` field is canonical and this is left empty).
    court_name_raw: str = ""
    bench: str | None = None  # archive bench slug, e.g. "manipurhc_pg" (HC only)
    # HC parquet's ``court_code`` column, e.g. ``"7~26"`` — needed to build the
    # bucket S3 path for PDF fetches. ``None`` for SCI rows.
    court_code: str | None = None
    judges: list[str] = field(default_factory=list)
    author_judge: str | None = None  # SCI only

    # Dates
    decision_date: date | None = None
    date_of_registration: date | None = None  # HC only

    # Parties (SCI only — HC encodes parties in title)
    petitioner: str | None = None
    respondent: str | None = None

    # Identifiers / status
    citation: str | None = None  # SCI only
    disposal_nature: str | None = None
    description: str | None = None

    # PDF access (raw refs for Phase 1; Phase 2 wraps in PdfRef)
    pdf_path: str | None = None  # SCI "path" or HC "pdf_link"
    available_languages: list[str] = field(default_factory=list)
    pdf_exists: bool | None = None

    # Provenance
    source: str = "archive"
    year: int | None = None


@dataclass
class AdvocateSearch(_Serializable):
    """An advocate search, with the advocate the portal resolved it to.

    The response envelope echoes back who it matched — a bar code of
    ``G/504/2011`` is answered with ``adv_name: "MR. HEMAL SHAH(6960)"`` —
    and that echo is the only confirmation available that a bar code is real.
    Nothing else validates one: the portal's own form takes the state part as
    free text on both High Court and district, so a wrong code is not an
    error, just a search that finds nothing.

    ``code`` is the portal's internal advocate id, **not** a bar number and
    not accepted as one.
    """

    #: As echoed, e.g. ``"MR. HEMAL SHAH(6960)"``. Empty when nothing matched.
    raw_name: str = ""
    #: The name with the bracketed id removed, e.g. ``"MR. HEMAL SHAH"``.
    name: str = ""
    #: The bracketed id, e.g. ``"6960"``. Absent on older district records.
    code: str = ""
    total_records: int = 0
    cases: list[CaseInfo] = field(default_factory=list)

    @property
    def found(self) -> bool:
        """Whether the portal recognised the advocate.

        True even with no cases: an advocate can exist and have nothing
        pending, and telling that apart from a mistyped bar code is the
        whole point of this class.
        """
        return bool(self.raw_name)

    def to_dict(self, *, exclude_none: bool = False) -> dict[str, Any]:
        """Override to carry ``found`` through serialization.

        It is a property, so the field-walking base implementation would drop
        the one flag this class exists to expose and leave every JSON
        consumer recomputing it. Same reason :class:`SearchResult` overrides
        for ``total_pages``.
        """
        result = super().to_dict(exclude_none=exclude_none)
        result["found"] = self.found
        return result


@dataclass
class PartyEntry(_Serializable):
    """A party to a case, with the advocate(s) appearing for them."""

    name: str
    advocate: str = ""


@dataclass
class ActEntry(_Serializable):
    """An act and the sections invoked under it."""

    act: str
    sections: str = ""


@dataclass
class HearingEntry(_Serializable):
    """One row of a case's hearing history.

    ``cause_list_type`` and ``judge`` are only populated where the portal
    supplies them — district court history tables carry a judge but no cause
    list type, High Court tables carry both but often leave judge blank.
    """

    hearing_date: date | None = None
    business_date: date | None = None
    purpose: str = ""
    judge: str = ""
    cause_list_type: str = ""


@dataclass
class CaseDetail(_Serializable):
    """Full case record from a CNR lookup.

    This is deliberately richer than :class:`CaseInfo`, which models a search
    *result*. A CNR lookup returns the whole case page — status, stage, the
    bench, every party with their advocates, the acts invoked, the complete
    hearing history and the orders — none of which a search response carries.

    Fields absent from a given portal are left at their default rather than
    guessed: district courts report ``court_number_and_judge`` where High
    Courts report ``coram`` plus ``bench_type``.
    """

    cnr_number: str = ""
    case_type: str = ""
    filing_number: str = ""
    filing_date: date | None = None
    registration_number: str = ""
    registration_date: date | None = None

    first_hearing_date: date | None = None
    next_hearing_date: date | None = None
    decision_date: date | None = None
    case_stage: str = ""
    status: str = ""

    coram: str = ""
    bench_type: str = ""
    court_number_and_judge: str = ""
    court_name: str = ""
    state: str = ""
    district: str = ""

    petitioners: list[PartyEntry] = field(default_factory=list)
    respondents: list[PartyEntry] = field(default_factory=list)
    acts: list[ActEntry] = field(default_factory=list)
    history: list[HearingEntry] = field(default_factory=list)
    orders: list[CaseOrder] = field(default_factory=list)

    @property
    def is_disposed(self) -> bool:
        """True when the portal has recorded a decision date."""
        return self.decision_date is not None


@dataclass
class CauseListEntry(_Serializable):
    """An entry from a court's cause list (daily schedule).

    Note: HC Services returns cause lists as PDFs per bench/judge.
    Use :class:`CauseListPDF` for the actual portal response.
    This model is retained for parsed/structured cause list data.
    """

    serial_number: int
    case_number: str
    case_type: str = ""
    petitioner: str = ""
    respondent: str = ""
    advocate_petitioner: str = ""
    advocate_respondent: str = ""
    court_number: str = ""
    judge: str = ""
    listing_date: date | None = None
    #: The day the matter was last in court, where the source gives it. The
    #: advocate cause list returns both dates per row — this one and the
    #: listing being queried — and a diary needs the pair to tell an
    #: adjournment from the hearing that produced it.
    business_date: date | None = None
    item_number: str = ""
    cnr_number: str = ""  # present on advocate cause lists, absent on PDFs
    purpose: str = ""  # e.g. "182-FOR FINAL HEARING"


@dataclass
class CauseListPDF(_Serializable):
    """A cause list PDF from HC Services.

    The portal returns a table of PDF links, one per bench/judge.
    Each entry contains the bench name, list type, and a URL to the PDF.
    """

    serial_number: int
    bench: str  # e.g. "Division Bench"
    cause_list_type: str = ""  # e.g. "COMPLETE CAUSE LIST"
    pdf_url: str = ""
    pdf_bytes: bytes | None = None


@dataclass
class SearchResult(_Serializable):
    """Paginated search result container."""

    items: list[CaseInfo | JudgmentResult | CauseListEntry] = field(default_factory=list)
    total_count: int = 0
    page: int = 1
    page_size: int = 10
    has_next: bool = False

    @property
    def total_pages(self) -> int:
        if self.page_size == 0:
            return 0
        return (self.total_count + self.page_size - 1) // self.page_size

    def to_dict(self, *, exclude_none: bool = False) -> dict[str, Any]:
        """Override to properly serialize nested items."""
        result = {
            "total_count": self.total_count,
            "page": self.page,
            "page_size": self.page_size,
            "has_next": self.has_next,
            "total_pages": self.total_pages,
            "items": [item.to_dict(exclude_none=exclude_none) for item in self.items],
        }
        return result
