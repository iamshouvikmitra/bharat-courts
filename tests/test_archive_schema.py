"""Unit tests for archive row → Judgment mapping.

The archive bucket has two distinct schemas (SCI vs HC). These tests use
inline row fixtures rather than hitting S3, so they run offline.
"""

from datetime import date, datetime

import pytest

from bharat_courts.archive.metadata import _ArchiveQuery
from bharat_courts.archive.schema import (
    _parse_date,
    _parse_languages,
    _split_judges,
    row_to_judgment,
)
from bharat_courts.courts import SUPREME_COURT, get_court_by_state_code
from bharat_courts.models import CourtType, Judgment

# ----- helpers ---------------------------------------------------------


def test_parse_date_handles_dd_mm_yyyy():
    assert _parse_date("17-10-1950") == date(1950, 10, 17)


def test_parse_date_handles_iso():
    assert _parse_date("1950-10-17") == date(1950, 10, 17)


def test_parse_date_handles_datetime():
    assert _parse_date(datetime(2020, 2, 11, 0, 0)) == date(2020, 2, 11)


def test_parse_date_returns_none_for_blank():
    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("garbage") is None


def test_split_judges_handles_comma_separated():
    judges = _split_judges("HARILAL KANIA, M PATANJALI SASTRI, MEHR CHAND MAHAJAN")
    assert judges == ["HARILAL KANIA", "M PATANJALI SASTRI", "MEHR CHAND MAHAJAN"]


def test_split_judges_filters_empty():
    assert _split_judges("A,,B") == ["A", "B"]


def test_split_judges_returns_empty_for_blank():
    assert _split_judges(None) == []
    assert _split_judges("") == []


def test_parse_languages_lowercases_and_splits():
    assert _parse_languages("ENG,HIN,PUN") == ["eng", "hin", "pun"]


def test_parse_languages_returns_empty_for_blank():
    assert _parse_languages(None) == []
    assert _parse_languages("") == []


# ----- SCI row mapping ------------------------------------------------


SCI_ROW = {
    "title": "SRI RANGA NILAYAM RAMA KRISHNA RAO versus KANDOKOLU CHELLA",
    "petitioner": "SRI RANGA NILAYAM RAMA KRISHNA RAO",
    "respondent": "KANDOKOLU CHELLA",
    "description": "",
    "judge": "BIJAN KUMAR MUKHERJEA, MEHR CHAND MAHAJAN",
    "author_judge": "None",
    "citation": "[1950] 1 S.C.R. 806",
    "case_id": "1950 INSC 25",
    "cnr": "ESCR010000301950",
    "decision_date": "17-10-1950",
    "disposal_nature": "Appeal(s) allowed",
    "court": "Supreme Court of India",
    "available_languages": "ENG,HIN,PUN",
    "raw_html": "<select>...</select>",
    "path": "1950_1_806_821",
    "nc_display": "1950INSC25",
    "scraped_at": "2025-06-12T21:11:33.644571",
    "year": "1950",
}


def test_row_to_judgment_sci_basic_fields():
    j = row_to_judgment(SCI_ROW)
    assert isinstance(j, Judgment)
    assert j.cnr == "ESCR010000301950"
    assert j.case_id == "1950 INSC 25"
    assert j.title.startswith("SRI RANGA NILAYAM")
    assert j.petitioner == "SRI RANGA NILAYAM RAMA KRISHNA RAO"
    assert j.respondent == "KANDOKOLU CHELLA"
    assert j.citation == "[1950] 1 S.C.R. 806"
    assert j.disposal_nature == "Appeal(s) allowed"
    assert j.source == "archive"
    assert j.year == 1950


def test_row_to_judgment_sci_resolves_supreme_court():
    j = row_to_judgment(SCI_ROW)
    assert j.court == SUPREME_COURT
    assert j.court_name_raw == "Supreme Court of India"


def test_row_to_judgment_sci_parses_date():
    j = row_to_judgment(SCI_ROW)
    assert j.decision_date == date(1950, 10, 17)


def test_row_to_judgment_sci_splits_judges():
    j = row_to_judgment(SCI_ROW)
    assert j.judges == ["BIJAN KUMAR MUKHERJEA", "MEHR CHAND MAHAJAN"]


def test_row_to_judgment_sci_filters_none_string_for_author():
    """The SCI parquet stores the string 'None' rather than null for missing author."""
    j = row_to_judgment(SCI_ROW)
    assert j.author_judge is None


def test_row_to_judgment_sci_parses_languages():
    j = row_to_judgment(SCI_ROW)
    assert j.available_languages == ["eng", "hin", "pun"]


def test_row_to_judgment_sci_carries_pdf_path():
    j = row_to_judgment(SCI_ROW)
    assert j.pdf_path == "1950_1_806_821"


# ----- HC row mapping -------------------------------------------------


HC_ROW = {
    "court_code": "14~25",
    "title": "CRP(C.R.P. Art.227)/6/2018 of NAOREM Vs LAIMUJAM",
    "description": "IN THE HIGH COURT OF MANIPUR AT IMPHAL",
    "judge": "HON'BLE THE CHIEF JUSTICE,HON'BLE MR JUSTICE KH NOBIN SINGH",
    "pdf_link": "court/cnrorders/manipurhc_pg/orders/MNHC010001072018_1_2020-02-11.pdf",
    "cnr": "MNHC010001072018",
    "date_of_registration": "19-01-2018",
    "decision_date": datetime(2020, 2, 11),
    "disposal_nature": "Dismissed as withdrawn",
    "court": "High Court of Manipur",
    "raw_html": "<button>...</button>",
    "pdf_exists": False,
    "year": "2020",
    "bench": "manipurhc_pg",
}


def test_row_to_judgment_hc_resolves_court_via_state_code():
    j = row_to_judgment(HC_ROW)
    assert j.court is not None
    assert j.court.state_code == "25"
    assert j.court.court_type == CourtType.HIGH_COURT
    # Sanity-check: state 25 is Manipur per courts.py
    assert j.court == get_court_by_state_code("25")


def test_row_to_judgment_hc_carries_bench_slug():
    j = row_to_judgment(HC_ROW)
    assert j.bench == "manipurhc_pg"


def test_row_to_judgment_hc_parses_dates():
    j = row_to_judgment(HC_ROW)
    assert j.decision_date == date(2020, 2, 11)
    assert j.date_of_registration == date(2018, 1, 19)


def test_row_to_judgment_hc_splits_judges():
    j = row_to_judgment(HC_ROW)
    assert j.judges == [
        "HON'BLE THE CHIEF JUSTICE",
        "HON'BLE MR JUSTICE KH NOBIN SINGH",
    ]


def test_row_to_judgment_hc_carries_pdf_link():
    j = row_to_judgment(HC_ROW)
    assert j.pdf_path == HC_ROW["pdf_link"]
    assert j.pdf_exists is False


def test_row_to_judgment_hc_has_no_sci_only_fields():
    j = row_to_judgment(HC_ROW)
    assert j.case_id is None
    assert j.citation is None
    assert j.petitioner is None
    assert j.respondent is None
    assert j.available_languages == []


def test_row_to_judgment_hc_unknown_state_returns_none_court():
    row = {**HC_ROW, "court_code": "99~99"}
    j = row_to_judgment(row)
    assert j.court is None
    assert j.court_name_raw == "High Court of Manipur"  # raw still preserved


def test_judgment_to_dict_serialises_nested_court_as_dict():
    """Regression: Court used to serialise as repr() inside Judgment.to_dict()."""
    j = row_to_judgment(SCI_ROW)
    d = j.to_dict()
    assert isinstance(d["court"], dict), f"expected nested dict, got {type(d['court'])}"
    assert d["court"]["name"] == "Supreme Court of India"
    assert d["court"]["code"] == "sci"
    assert d["court"]["court_type"] == "supreme_court"


# ----- query builder --------------------------------------------------


@pytest.fixture
def query():
    """An _ArchiveQuery without a live connection (we only test SQL building)."""
    return _ArchiveQuery()


def test_sci_query_year_single(query):
    sql, params = query._build_sci_query(
        year=2020, judge=None, party=None, citation=None, cnr=None, limit=10
    )
    assert "year = ?" in sql
    assert params == ["2020"]


def test_sci_query_year_range(query):
    sql, params = query._build_sci_query(
        year=(2018, 2024), judge=None, party=None, citation=None, cnr=None, limit=10
    )
    assert "BETWEEN ? AND ?" in sql
    assert params == [2018, 2024]


def test_sci_query_combines_filters(query):
    sql, params = query._build_sci_query(
        year=2020,
        judge="chandra",
        party="state",
        citation="SCC",
        cnr=None,
        limit=5,
    )
    assert "judge ILIKE ?" in sql
    assert "petitioner ILIKE ? OR respondent ILIKE ? OR title ILIKE ?" in sql
    assert "citation ILIKE ?" in sql
    assert params == ["2020", "%chandra%", "%state%", "%state%", "%state%", "%SCC%"]


def test_sci_query_no_filters_uses_true_clause(query):
    sql, params = query._build_sci_query(
        year=None, judge=None, party=None, citation=None, cnr=None, limit=10
    )
    assert "WHERE TRUE" in sql
    assert params == []


def test_hc_query_filters_by_state_code_via_partition(query):
    delhi = get_court_by_state_code("26")
    sql, params = query._build_hc_query(
        court=delhi, year=2020, judge=None, party=None, cnr=None, limit=10
    )
    # Should filter on the partition column so DuckDB can prune.
    assert "SPLIT_PART(court, '_', 2) = ?" in sql
    assert "26" in params
    assert "2020" in params


def test_hc_query_party_falls_back_to_title(query):
    sql, params = query._build_hc_query(
        court=None, year=None, judge=None, party="bank", cnr=None, limit=10
    )
    # HC parquet has no petitioner/respondent — must search title only.
    assert "title ILIKE ?" in sql
    assert "petitioner" not in sql
    assert params == ["%bank%"]


def test_hc_query_supreme_court_input_skips_state_filter(query):
    """Passing SCI to the HC builder shouldn't add a state filter."""
    sql, params = query._build_hc_query(
        court=SUPREME_COURT, year=None, judge=None, party=None, cnr=None, limit=10
    )
    assert "SPLIT_PART" not in sql
    assert params == []
