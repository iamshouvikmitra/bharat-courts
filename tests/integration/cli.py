#!/usr/bin/env python3
"""Live checks for the ``bharat-courts`` command line.

Runs the CLI as a subprocess (exactly as a user would) across every command
group — ``courts``, ``hcservices``, ``districtcourts``, ``archive``, ``sci``,
``find`` — and checks that ``--json`` output is well-formed and populated.
Only one check burns a CAPTCHA (``find --text``); the rest hit CAPTCHA-free
endpoints or S3.

Usage::

    pip install -e '.[all]'
    python tests/integration/cli.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import Check, Suite, require, rotate  # noqa: E402

require("click", "cli")
require("duckdb", "archive")

suite = Suite("CLI live checks", results_dir="/tmp/bharat_courts_cli_test", backend="cli")

HC = rotate(["delhi", "bombay", "allahabad", "karnataka", "madras", "gujarat", "kerala", "punjab"])[
    0
]
SMALL_HC = rotate(["manipur", "sikkim", "meghalaya", "tripura"])[0]
PHRASE = rotate(
    ["anticipatory bail", "specific performance", "writ of mandamus", "arbitral award"]
)[0]


def run_cli(*args: str, timeout: int = 240) -> subprocess.CompletedProcess:
    """Invoke the CLI entry point in a fresh interpreter."""
    cmd = [sys.executable, "-c", "from bharat_courts.cli import main; main()", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def run_json(c: Check, *args: str, timeout: int = 240):
    proc = run_cli("--json", *args, timeout=timeout)
    c.details["cmd"] = "bharat-courts --json " + " ".join(args)
    if proc.returncode != 0:
        raise AssertionError(f"exit {proc.returncode}: {proc.stderr.strip()[-400:]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise AssertionError(f"stdout is not JSON ({e}): {proc.stdout[:200]!r}") from e


@suite.check("version", "cli.version")
def check_version(c: Check) -> None:
    from bharat_courts import __version__

    proc = run_cli("version")
    assert proc.returncode == 0, proc.stderr
    c.details["stdout"] = proc.stdout.strip()
    assert __version__ in proc.stdout
    c.passed = True


@suite.check("courts --type hc (offline)", "cli.courts")
def check_courts(c: Check) -> None:
    data = run_json(c, "courts", "--type", "hc")
    c.details["count"] = len(data)
    assert len(data) >= 20 and all(d["court_type"] == "high_court" for d in data)
    c.passed = True


@suite.check(f"hcservices benches / case-types ({HC})", "cli.hcservices")
def check_hcservices(c: Check) -> None:
    benches = run_json(c, "hcservices", "benches", HC)
    c.details["benches"] = benches
    assert benches, "no benches"
    types = run_json(c, "hcservices", "case-types", HC)
    c.details["case_types"] = len(types)
    assert len(types) > 10
    c.passed = True


@suite.check("districtcourts states / districts", "cli.districtcourts")
def check_districtcourts(c: Check) -> None:
    states = run_json(c, "districtcourts", "states")
    c.details["states"] = len(states)
    assert len(states) >= 36
    districts = run_json(c, "districtcourts", "districts", "--state", "8")
    c.details["bihar_districts"] = len(districts)
    assert len(districts) > 10
    c.passed = True


@suite.check(f"archive count / query ({SMALL_HC} 2020)", "cli.archive")
def check_archive(c: Check) -> None:
    count = run_json(c, "archive", "count", "--court", SMALL_HC, "--year", "2020")
    c.details["count"] = count
    assert count.get("hc", 0) > 0
    rows = run_json(c, "archive", "query", "--court", SMALL_HC, "--year", "2020", "--limit", "3")
    c.details["query_rows"] = len(rows)
    assert len(rows) == 3 and all(r.get("cnr") for r in rows)
    cache = run_cli("archive", "cache")
    assert cache.returncode == 0, cache.stderr
    c.details["cache"] = cache.stdout.strip().splitlines()[0] if cache.stdout.strip() else "(empty)"
    c.passed = True


@suite.check("archive get --cnr", "cli.archive_get")
def check_archive_get(c: Check) -> None:
    data = run_json(c, "archive", "get", "--cnr", "DLHC010230802020")
    row = data[0] if isinstance(data, list) else data
    c.details["title"] = (row.get("title") or "")[:60]
    assert row.get("cnr") == "DLHC010230802020"
    c.passed = True


@suite.check("find --cnr (archive route)", "cli.find")
def check_find_cnr(c: Check) -> None:
    rows = run_json(c, "find", "--cnr", "DLHC010230802020")
    c.details["rows"] = len(rows)
    assert len(rows) == 1 and rows[0]["source"] == "archive"
    c.passed = True


@suite.check(f"find --text (live route, CAPTCHA) — {PHRASE!r}", "cli.find(live)")
def check_find_text(c: Check) -> None:
    rows = run_json(c, "find", "--text", PHRASE, "--limit", "3", timeout=300)
    c.details["rows"] = len(rows)
    assert rows and all(r["source"] == "live" for r in rows)
    c.details["first"] = (rows[0].get("title") or "")[:60]
    c.passed = True


@suite.check("sci recent --limit 3", "cli.sci")
def check_sci(c: Check) -> None:
    rows = run_json(c, "sci", "recent", "--limit", "3")
    c.details["rows"] = len(rows)
    assert rows and rows[0].get("title")
    c.passed = True


if __name__ == "__main__":
    suite.main()
