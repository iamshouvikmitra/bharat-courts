"""Tests for the bharat-courts CLI.

All tests are offline. Network-touching subcommands are exercised by
patching the underlying SDK client method to return canned data.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from click.testing import CliRunner

from bharat_courts import cli as cli_module
from bharat_courts._version import __version__
from bharat_courts.cli import main
from bharat_courts.models import (
    CaseInfo,
    CaseOrder,
    JudgmentResult,
    SearchResult,
)

# ---------------------------------------------------------------------------
# Top-level commands
# ---------------------------------------------------------------------------


def test_version_subcommand():
    runner = CliRunner()
    result = runner.invoke(main, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_version_flag():
    runner = CliRunner()
    result = runner.invoke(main, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_courts_command():
    runner = CliRunner()
    result = runner.invoke(main, ["courts"])
    assert result.exit_code == 0
    assert "Delhi" in result.output
    assert "Supreme Court" in result.output


def test_courts_hc_filter():
    runner = CliRunner()
    result = runner.invoke(main, ["courts", "--type", "hc"])
    assert result.exit_code == 0
    assert "Delhi" in result.output
    assert "Supreme Court of India" not in result.output


def test_courts_sc_filter():
    runner = CliRunner()
    result = runner.invoke(main, ["courts", "--type", "sc"])
    assert result.exit_code == 0
    assert "Supreme Court" in result.output


def test_courts_json_is_valid_json():
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "courts", "--type", "sc"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["code"] == "sci"
    assert payload[0]["court_type"] == "supreme_court"


def test_top_level_help_lists_groups():
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    for group in (
        "hcservices",
        "districtcourts",
        "calcuttahc",
        "judgments",
        "sci",
        "courts",
        "version",
    ):
        assert group in result.output


# ---------------------------------------------------------------------------
# hcservices group
# ---------------------------------------------------------------------------


def test_hcservices_search_unknown_court():
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "hcservices",
            "search",
            "nonexistent-court",
            "--case-type",
            "WP",
            "--case-number",
            "1",
            "--year",
            "2024",
        ],
    )
    assert result.exit_code == 1
    assert "Unknown court" in result.output


def test_hcservices_orders_unknown_court():
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "hcservices",
            "orders",
            "no-such-court",
            "--case-type",
            "1",
            "--case-number",
            "1",
            "--year",
            "2024",
        ],
    )
    assert result.exit_code == 1
    assert "Unknown court" in result.output


def _patch_async_method(monkeypatch, client_path: str, method: str, fake):
    """Replace an async method on a client class with an async lambda
    that returns ``fake``."""
    mod_name, _, cls_name = client_path.rpartition(".")
    mod = __import__(mod_name, fromlist=[cls_name])
    cls = getattr(mod, cls_name)

    async def _impl(self, *args, **kwargs):
        return fake

    monkeypatch.setattr(cls, method, _impl, raising=True)


def test_hcservices_benches_human_output(monkeypatch):
    _patch_async_method(
        monkeypatch,
        "bharat_courts.hcservices.client.HCServicesClient",
        "list_benches",
        {"1": "Principal Bench at Delhi", "2": "Some Other Bench"},
    )
    runner = CliRunner()
    result = runner.invoke(main, ["hcservices", "benches", "delhi"])
    assert result.exit_code == 0, result.output
    assert "Principal Bench at Delhi" in result.output
    assert "Some Other Bench" in result.output


def test_hcservices_benches_json(monkeypatch):
    _patch_async_method(
        monkeypatch,
        "bharat_courts.hcservices.client.HCServicesClient",
        "list_benches",
        {"1": "Principal Bench at Delhi"},
    )
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "hcservices", "benches", "delhi"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == {"1": "Principal Bench at Delhi"}


def test_hcservices_case_types(monkeypatch):
    _patch_async_method(
        monkeypatch,
        "bharat_courts.hcservices.client.HCServicesClient",
        "list_case_types",
        {"134": "W.P.(C)(CIVIL WRITS)-134"},
    )
    runner = CliRunner()
    result = runner.invoke(main, ["hcservices", "case-types", "delhi"])
    assert result.exit_code == 0, result.output
    assert "W.P.(C)" in result.output
    assert "134" in result.output


def test_hcservices_search_json(monkeypatch):
    fake = [
        CaseInfo(
            case_number="3/2024",
            case_type="W.P.(C)",
            cnr_number="DLHC010582482024",
            petitioner="ALICE",
            respondent="BOB",
            status="Pending",
            registration_date=date(2024, 1, 5),
        )
    ]
    _patch_async_method(
        monkeypatch,
        "bharat_courts.hcservices.client.HCServicesClient",
        "case_status",
        fake,
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--json",
            "hcservices",
            "search",
            "delhi",
            "--case-type",
            "134",
            "--case-number",
            "3",
            "--year",
            "2024",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["cnr_number"] == "DLHC010582482024"
    assert data[0]["registration_date"] == "2024-01-05"


# ---------------------------------------------------------------------------
# districtcourts group
# ---------------------------------------------------------------------------


def test_districtcourts_states_human(monkeypatch):
    _patch_async_method(
        monkeypatch,
        "bharat_courts.districtcourts.client.DistrictCourtClient",
        "list_states",
        {"8": "Bihar", "26": "Delhi"},
    )
    runner = CliRunner()
    result = runner.invoke(main, ["districtcourts", "states"])
    assert result.exit_code == 0, result.output
    assert "Bihar" in result.output
    assert "Delhi" in result.output


def test_districtcourts_states_json(monkeypatch):
    _patch_async_method(
        monkeypatch,
        "bharat_courts.districtcourts.client.DistrictCourtClient",
        "list_states",
        {"8": "Bihar"},
    )
    runner = CliRunner()
    result = runner.invoke(main, ["--json", "districtcourts", "states"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data == {"8": "Bihar"}


def test_districtcourts_districts(monkeypatch):
    _patch_async_method(
        monkeypatch,
        "bharat_courts.districtcourts.client.DistrictCourtClient",
        "list_districts",
        {"1": "Patna", "2": "Gaya"},
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        ["districtcourts", "districts", "--state", "8"],
    )
    assert result.exit_code == 0, result.output
    assert "Patna" in result.output
    assert "Gaya" in result.output


def test_districtcourts_complexes(monkeypatch):
    _patch_async_method(
        monkeypatch,
        "bharat_courts.districtcourts.client.DistrictCourtClient",
        "list_complexes",
        {"1080010@N@Y": "District Court Patna"},
    )
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "districtcourts",
            "complexes",
            "--state",
            "8",
            "--dist",
            "1",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "District Court Patna" in result.output


# ---------------------------------------------------------------------------
# calcuttahc group
# ---------------------------------------------------------------------------


def test_calcuttahc_search_human(monkeypatch):
    fake_case = CaseInfo(
        case_number="WPA/12886/2024",
        case_type="WPA",
        cnr_number="WBCHCA0239512024",
        petitioner="ALICE",
        respondent="UNION OF INDIA",
        court_name="Calcutta High Court - Appellate Side",
    )
    fake_orders = [
        CaseOrder(
            order_date=date(2024, 5, 10),
            order_type="Order",
            judge="J. SOMEONE",
            neutral_citation="2024:CHC-AS:1277",
            pdf_url="https://example/foo.pdf",
        )
    ]

    async def _impl(self, *args, **kwargs):
        return fake_case, fake_orders

    from bharat_courts.calcuttahc.client import CalcuttaHCClient

    monkeypatch.setattr(CalcuttaHCClient, "search_orders", _impl, raising=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "calcuttahc",
            "search",
            "--case-type",
            "12",
            "--case-number",
            "12886",
            "--year",
            "2024",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "WPA/12886/2024" in result.output
    assert "ALICE" in result.output
    assert "2024:CHC-AS:1277" in result.output


def test_calcuttahc_search_json(monkeypatch):
    fake_case = CaseInfo(
        case_number="WPA/12886/2024",
        case_type="WPA",
        cnr_number="WBCHCA0239512024",
        petitioner="ALICE",
        respondent="UNION OF INDIA",
    )
    fake_orders = [
        CaseOrder(
            order_date=date(2024, 5, 10),
            order_type="Order",
            judge="J. SOMEONE",
            neutral_citation="2024:CHC-AS:1277",
        )
    ]

    async def _impl(self, *args, **kwargs):
        return fake_case, fake_orders

    from bharat_courts.calcuttahc.client import CalcuttaHCClient

    monkeypatch.setattr(CalcuttaHCClient, "search_orders", _impl, raising=True)

    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "--json",
            "calcuttahc",
            "search",
            "--case-type",
            "12",
            "--case-number",
            "12886",
            "--year",
            "2024",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["case_info"]["cnr_number"] == "WBCHCA0239512024"
    assert isinstance(data["orders"], list)
    assert data["orders"][0]["order_date"] == "2024-05-10"


# ---------------------------------------------------------------------------
# judgments group
# ---------------------------------------------------------------------------


def test_judgments_search_human(monkeypatch):
    fake_sr = SearchResult(
        items=[
            JudgmentResult(
                title="State vs Foo",
                court_name="Delhi High Court",
                case_number="WP/1/2024",
                judgment_date=date(2024, 6, 1),
            )
        ],
        total_count=1,
        page=1,
        page_size=10,
        has_next=False,
    )
    _patch_async_method(
        monkeypatch,
        "bharat_courts.judgments.client.JudgmentSearchClient",
        "search",
        fake_sr,
    )

    runner = CliRunner()
    result = runner.invoke(main, ["judgments", "search", "--text", "section 498A"])
    assert result.exit_code == 0, result.output
    assert "State vs Foo" in result.output
    assert "WP/1/2024" in result.output


# ---------------------------------------------------------------------------
# sci group
# ---------------------------------------------------------------------------


def test_sci_recent_human(monkeypatch):
    fake = [
        JudgmentResult(
            title="UoI vs Bar",
            court_name="Supreme Court of India",
            case_number="C.A. 1/2024",
            judgment_date=date(2024, 6, 15),
            source_id="12345",
        )
    ]
    _patch_async_method(
        monkeypatch,
        "bharat_courts.sci.client.SCIClient",
        "list_recent_judgments",
        fake,
    )
    runner = CliRunner()
    result = runner.invoke(main, ["sci", "recent", "--limit", "1"])
    assert result.exit_code == 0, result.output
    assert "UoI vs Bar" in result.output
    assert "Diary: 12345" in result.output


# ---------------------------------------------------------------------------
# Helper coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected_prefix",
    [
        ("WPA/12886/2024", "WPA_12886_2024"),
        ("hello world!", "hello_world"),
        ("///", "unnamed_"),
        ("  spaced name  ", "spaced_name"),
    ],
)
def test_safe_filename(raw, expected_prefix):
    out = cli_module._safe_filename(raw)
    assert out.startswith(expected_prefix) or out == expected_prefix
