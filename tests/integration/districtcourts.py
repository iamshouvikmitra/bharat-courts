#!/usr/bin/env python3
"""Live integration test for District Courts client.

Tests against services.ecourts.gov.in using Bihar (state_code=8) as
a well-populated state with active district courts.

Usage:
    cd bharat-courts
    source .venv/bin/activate
    python tests/integration/districtcourts.py

Tests:
  1. List states (offline)
  2. List districts for Bihar (no CAPTCHA)
  3. List court complexes for Patna (no CAPTCHA)
  4. List case types (no CAPTCHA)
  5. Case status by party name (CAPTCHA + retry)
  6. Case status by act — Delhi / Karkardooma, CMM establishment (CAPTCHA)
"""

import asyncio
import json
import sys
import traceback
from datetime import date
from pathlib import Path

# --- Setup ---

RESULTS_DIR = Path("/tmp/bharat_courts_district_test")
RESULTS_DIR.mkdir(exist_ok=True)

# Try OCR solver first, fall back to ONNX
solver = None
try:
    from bharat_courts.captcha.ocr import OCRCaptchaSolver

    solver = OCRCaptchaSolver()
    print("Using OCR CAPTCHA solver (ddddocr)")
except ImportError:
    try:
        from bharat_courts.captcha.onnx import ONNXCaptchaSolver

        solver = ONNXCaptchaSolver()
        print("Using ONNX CAPTCHA solver")
    except ImportError:
        print("ERROR: No CAPTCHA solver available.")
        print("Install one: pip install 'bharat-courts[ocr]' or pip install 'bharat-courts[onnx]'")
        sys.exit(1)


def save_json(name: str, data) -> Path:
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    return path


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error = ""
        self.details = {}

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        s = f"[{status}] {self.name}"
        if self.error:
            s += f" — {self.error}"
        if self.details:
            for k, v in self.details.items():
                s += f"\n       {k}: {v}"
        return s


results: list[TestResult] = []


# --- Test Functions ---


async def test_list_states():
    """Test 1: Live state list + drift check against the bundled snapshot.

    The portal's state codes are internal and have drifted wholesale before
    (13/36 stale, #25) — so this doubles as a drift alarm: if the live
    dropdown ever disagrees with DISTRICT_STATES, this test fails and the
    snapshot needs re-verifying.
    """
    t = TestResult("List States (live + snapshot drift check)")
    try:
        from bharat_courts.districtcourts.client import DistrictCourtClient
        from bharat_courts.districtcourts.endpoints import DISTRICT_STATES

        async with DistrictCourtClient(captcha_solver=solver) as client:
            live = await client.list_states()

        t.details["total_states"] = len(live)
        t.details["delhi_code"] = next((k for k, v in live.items() if v == "Delhi"), None)

        assert len(live) >= 36, f"Too few states: {len(live)}"
        assert live.get("26") == "Delhi"
        assert live.get("8") == "Bihar"

        snapshot = {v: k for k, v in DISTRICT_STATES.items()}
        drift = {
            code: (name, snapshot.get(code))
            for code, name in live.items()
            if snapshot.get(code) != name
        }
        t.details["drift"] = drift or "none"
        assert not drift, f"DISTRICT_STATES snapshot has drifted from the live portal: {drift}"

        t.passed = True
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_list_districts():
    """Test 2: List districts for Bihar."""
    t = TestResult("List Districts (Bihar, state_code=8)")
    try:
        from bharat_courts.districtcourts.client import DistrictCourtClient

        async with DistrictCourtClient(captcha_solver=solver) as client:
            districts = await client.list_districts("8")
            t.details["district_count"] = len(districts)
            t.details["sample"] = dict(list(districts.items())[:5])
            assert len(districts) > 10, f"Too few districts: {len(districts)}"
            save_json("districts_bihar", districts)
            t.passed = True
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_list_complexes():
    """Test 3: List court complexes for Patna."""
    t = TestResult("List Court Complexes (Bihar/Patna)")
    try:
        from bharat_courts.districtcourts.client import DistrictCourtClient
        from bharat_courts.districtcourts.parser import parse_complex_value

        async with DistrictCourtClient(captcha_solver=solver) as client:
            complexes = await client.list_complexes("8", "1")  # Bihar, Patna
            t.details["complex_count"] = len(complexes)
            t.details["complexes"] = complexes
            assert len(complexes) > 0, "No court complexes found"

            # Parse the first complex value to verify format
            first_val = list(complexes.keys())[0]
            code, ests, needs_est = parse_complex_value(first_val)
            t.details["first_code"] = code
            t.details["first_ests"] = ests
            t.details["needs_establishment"] = needs_est

            save_json("complexes_patna", complexes)
            t.passed = True
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_list_case_types():
    """Test 4: List case types for a court complex."""
    t = TestResult("List Case Types (Bihar/Patna/Civil Court Patna Sadar)")
    try:
        from bharat_courts.districtcourts.client import DistrictCourtClient
        from bharat_courts.districtcourts.parser import parse_complex_value

        async with DistrictCourtClient(captcha_solver=solver) as client:
            # First get complexes
            complexes = await client.list_complexes("8", "1")
            if not complexes:
                t.error = "No complexes found"
                results.append(t)
                return

            # Pick last complex (Patna Sadar)
            complex_val = list(complexes.keys())[-1]
            complex_code, ests, needs_est = parse_complex_value(complex_val)

            est_code = ests[0] if ests and needs_est else ""

            case_types = await client.list_case_types("8", "1", complex_code, est_code)
            t.details["case_type_count"] = len(case_types)
            t.details["sample"] = dict(list(case_types.items())[:5])
            assert len(case_types) > 0, "No case types found"

            save_json("case_types_patna", case_types)
            t.passed = True
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_case_status_by_party():
    """Test 5: Case status search by party name (CAPTCHA)."""
    t = TestResult("Case Status by Party (Bihar/Patna, 'Union of India', 2024)")
    try:
        from bharat_courts.districtcourts.client import DistrictCourtClient
        from bharat_courts.districtcourts.parser import parse_complex_value

        async with DistrictCourtClient(captcha_solver=solver) as client:
            # Get a valid court complex
            complexes = await client.list_complexes("8", "1")
            if not complexes:
                t.error = "No complexes found"
                results.append(t)
                return

            complex_val = list(complexes.keys())[-1]
            complex_code, ests, needs_est = parse_complex_value(complex_val)
            est_code = ests[0] if ests and needs_est else ""

            # NB: use a specific party name, not a generic word like "state".
            # Over-broad terms match tens of thousands of rows and the eCourts
            # server times out generating them (ReadTimeout ~190s), which looks
            # like an SDK failure but is really a degenerate query. "Union of
            # India" is a party to a bounded, always-present set of cases.
            cases = await client.case_status_by_party(
                state_code="8",
                dist_code="1",
                court_complex_code=complex_code,
                est_code=est_code,
                party_name="Union of India",
                year="2024",
            )

            t.details["cases_found"] = len(cases)
            if cases:
                first = cases[0]
                t.details["first_case_number"] = first.case_number
                t.details["first_petitioner"] = first.petitioner
                t.details["first_respondent"] = first.respondent
                save_json(
                    "case_status_party",
                    [c.to_dict(exclude_none=True) for c in cases[:10]],
                )
            t.passed = len(cases) > 0
            if not t.passed:
                t.error = "No cases found (may be CAPTCHA related)"
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_case_status_by_act():
    """Test 6: NI Act s.138 pending at Karkardooma's CMM establishment.

    Delhi rather than Bihar because this is where the act search was first
    verified live. The establishment is found by name: an act search covers
    one establishment, and cheque cases sit with the magistrates.
    """
    t = TestResult("Case Status by Act (Delhi/Karkardooma CMM, NI Act s.138)")
    try:
        from bharat_courts.districtcourts.client import DistrictCourtClient
        from bharat_courts.districtcourts.parser import parse_complex_value

        async with DistrictCourtClient(captcha_solver=solver) as client:
            complexes = await client.list_complexes("26", "1")
            complex_val = next(v for v, n in complexes.items() if "karkardooma" in n.lower())
            complex_code, _, _ = parse_complex_value(complex_val)
            ests = await client.list_establishments("26", "1", complex_code)
            est_code = next(c for c, n in ests.items() if "metropolitan magistrate" in n.lower())

            acts = await client.list_acts("26", "1", complex_code, est_code, search="negotiable")
            t.details["acts"] = acts
            act_code = next(c for c, n in acts.items() if "negotiable" in n.lower())

            cases = await client.case_status_by_act(
                state_code="26",
                dist_code="1",
                court_complex_code=complex_code,
                est_code=est_code,
                act_code=act_code,
                section="138",
            )
            t.details["cases_found"] = len(cases)
            if cases:
                save_json("case_status_act", [c.to_dict(exclude_none=True) for c in cases[:10]])
            t.passed = len(cases) > 0
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


# --- Main ---


async def run_all():
    print("=" * 60)
    print("  bharat-courts — District Courts Live Test")
    print(f"  Date: {date.today().isoformat()}")
    print(f"  Results dir: {RESULTS_DIR}")
    print("=" * 60)
    print()

    test_funcs = [
        ("1/6", "List States", test_list_states),
        ("2/6", "List Districts", test_list_districts),
        ("3/6", "List Complexes", test_list_complexes),
        ("4/6", "List Case Types", test_list_case_types),
        ("5/6", "Case Status by Party", test_case_status_by_party),
        ("6/6", "Case Status by Act", test_case_status_by_act),
    ]

    for label, name, func in test_funcs:
        print(f"[{label}] {name}...")
        if asyncio.iscoroutinefunction(func):
            await func()
        else:
            func()
        print(f"  {results[-1]}")
        print()

    # Summary
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    print("=" * 60)
    print(f"  Results: {passed}/{total} passed")
    print(f"  All outputs saved to: {RESULTS_DIR}")
    print("=" * 60)

    save_json(
        "test_summary",
        {
            "date": date.today().isoformat(),
            "passed": passed,
            "total": total,
            "tests": [
                {"name": r.name, "passed": r.passed, "error": r.error, "details": str(r.details)}
                for r in results
            ],
        },
    )

    return passed == total


def main():
    success = asyncio.run(run_all())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
