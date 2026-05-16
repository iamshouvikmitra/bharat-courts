"""Row → :class:`Judgment` mapping for SCI and HC parquet rows.

The two buckets have different schemas. Common columns: ``cnr``, ``title``,
``description``, ``judge``, ``decision_date``, ``disposal_nature``, ``court``.

Source-specific:

================  ===========  ==========
field             SCI          HC
================  ===========  ==========
petitioner        yes          no (in title)
respondent        yes          no (in title)
citation          yes          no
case_id           yes          no
author_judge      yes          no
available_lang    "ENG,HIN"    no
path              yes          no
date_of_reg       no           yes
pdf_link          no           yes
pdf_exists        no           yes (bool)
court_code        no           "X~Y"
decision_date     "DD-MM-YYYY" timestamp
================  ===========  ==========

The mapping normalises dates, splits judge strings, and resolves the bench
to a :class:`bharat_courts.Court` via the courts registry.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from bharat_courts.courts import SUPREME_COURT, get_court_by_state_code
from bharat_courts.models import Court, Judgment


def _parse_date(value: Any) -> date | None:
    """Accept ``date``, ``datetime``, ``"DD-MM-YYYY"`` or ``"YYYY-MM-DD"``."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def _split_judges(value: Any) -> list[str]:
    """Split the free-form ``judge`` column into a list of names."""
    if not value or not isinstance(value, str):
        return []
    parts = [p.strip() for p in value.split(",")]
    return [p for p in parts if p]


def _parse_languages(value: Any) -> list[str]:
    """``"ENG,HIN,PUN"`` → ``["eng", "hin", "pun"]``."""
    if not value or not isinstance(value, str):
        return []
    return [p.strip().lower() for p in value.split(",") if p.strip()]


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
    return None


def _resolve_hc_court(court_code: str | None) -> tuple[Court | None, str]:
    """``"14~25"`` → (Manipur HC, "14~25"). Returns (None, raw) on unknown."""
    if not court_code or "~" not in court_code:
        return None, court_code or ""
    state_code = court_code.split("~", 1)[1]
    return get_court_by_state_code(state_code), court_code


def row_to_judgment(row: dict[str, Any]) -> Judgment:
    """Map a parquet row dict (SCI or HC schema) to a :class:`Judgment`.

    The mapper distinguishes sources by the presence of ``court_code``
    (HC-only) and ``case_id`` / ``path`` (SCI-only).
    """
    is_hc = "court_code" in row and row.get("court_code")

    if is_hc:
        court, raw_court_code = _resolve_hc_court(row.get("court_code"))
        return Judgment(
            cnr=row.get("cnr"),
            title=row.get("title"),
            court=court,
            court_name_raw=row.get("court") or "",
            bench=row.get("bench"),
            court_code=raw_court_code or None,
            judges=_split_judges(row.get("judge")),
            decision_date=_parse_date(row.get("decision_date")),
            date_of_registration=_parse_date(row.get("date_of_registration")),
            disposal_nature=row.get("disposal_nature"),
            description=row.get("description"),
            pdf_path=row.get("pdf_link"),
            pdf_exists=_parse_bool(row.get("pdf_exists")),
            source="archive",
            year=int(row["year"]) if row.get("year") else None,
        )

    # SCI shape
    author_judge = row.get("author_judge")
    if author_judge in (None, "None"):
        author_judge = None
    return Judgment(
        cnr=row.get("cnr"),
        case_id=row.get("case_id"),
        title=row.get("title"),
        court=SUPREME_COURT,
        court_name_raw=row.get("court") or "",
        judges=_split_judges(row.get("judge")),
        author_judge=author_judge,
        decision_date=_parse_date(row.get("decision_date")),
        petitioner=row.get("petitioner"),
        respondent=row.get("respondent"),
        citation=row.get("citation"),
        disposal_nature=row.get("disposal_nature"),
        description=row.get("description"),
        pdf_path=row.get("path"),
        available_languages=_parse_languages(row.get("available_languages")),
        source="archive",
        year=int(row["year"]) if row.get("year") else None,
    )
