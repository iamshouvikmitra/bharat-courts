#!/usr/bin/env python3
"""Comprehensive live test of bharat-courts against real eCourts portals.

Uses the package's HCServicesClient with ddddocr for automatic CAPTCHA solving.
Each test creates a fresh session to avoid CAPTCHA session pinning issues.

Usage:
    cd bharat-courts
    source .venv/bin/activate
    python examples/live_test_all.py

Tests:
  1. Court registry (offline)
  2. HC Services: bench listing (no CAPTCHA)
  3. HC Services: case type listing (no CAPTCHA)
  4. HC Services: cause list (CAPTCHA + retry)
  5. HC Services: case status by party name (CAPTCHA + retry)
  6. HC Services: case status by case number (CAPTCHA + retry)
  7. JSON serialization of all results
  8. OCR CAPTCHA solver stress test
"""

import asyncio
import json
import sys
import traceback
from datetime import date
from pathlib import Path

# --- Setup ---

RESULTS_DIR = Path("/tmp/bharat_courts_test")
RESULTS_DIR.mkdir(exist_ok=True)

# ddddocr for automatic CAPTCHA solving
try:
    import ddddocr  # noqa: F401
except ImportError:
    print("ERROR: ddddocr not installed. Run: pip install 'ddddocr>=1.5.5,<1.6'")
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


def test_court_registry():
    """Test 1: Offline court registry."""
    t = TestResult("Court Registry")
    try:
        from bharat_courts.courts import get_court, list_all_courts, list_high_courts

        all_courts = list_all_courts()
        hcs = list_high_courts()
        delhi = get_court("delhi")
        bombay = get_court("bombay")
        sci = get_court("sci")

        assert delhi is not None and delhi.state_code == "26"
        assert bombay is not None and bombay.state_code == "1"
        assert sci is not None

        t.details["total_courts"] = len(all_courts)
        t.details["high_courts"] = len(hcs)
        t.details["delhi_code"] = delhi.state_code
        t.details["json_sample"] = delhi.to_json()
        t.passed = True
    except Exception as e:
        t.error = str(e)
    results.append(t)


async def test_bench_listing():
    """Test 2: Bench listing (no CAPTCHA)."""
    t = TestResult("Bench Listing (Delhi, Bombay, Allahabad)")
    try:
        from bharat_courts.captcha.ocr import OCRCaptchaSolver
        from bharat_courts.courts import get_court
        from bharat_courts.hcservices.client import HCServicesClient

        solver = OCRCaptchaSolver()
        async with HCServicesClient(captcha_solver=solver) as client:
            courts = [("Delhi", "delhi"), ("Bombay", "bombay"), ("Allahabad", "allahabad")]
            for name, slug in courts:
                court = get_court(slug)
                benches = await client.list_benches(court)
                t.details[f"{name} benches"] = benches
                assert len(benches) > 0, f"No benches for {name}"

        t.passed = True
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
    results.append(t)


async def test_case_type_listing():
    """Test 3: Case type listing (no CAPTCHA)."""
    t = TestResult("Case Type Listing (Delhi HC)")
    try:
        from bharat_courts.captcha.ocr import OCRCaptchaSolver
        from bharat_courts.courts import get_court
        from bharat_courts.hcservices.client import HCServicesClient

        solver = OCRCaptchaSolver()
        async with HCServicesClient(captcha_solver=solver) as client:
            delhi = get_court("delhi")
            case_types = await client.list_case_types(delhi)
            t.details["count"] = len(case_types)

            # Find W.P.(C)
            wp_code = None
            for code, name in case_types.items():
                if "W.P.(C)" in name:
                    wp_code = code
                    break
            t.details["W.P.(C) code"] = wp_code
            t.details["sample"] = dict(list(case_types.items())[:5])

            assert len(case_types) > 10, f"Too few case types: {len(case_types)}"
            assert wp_code is not None, "W.P.(C) not found"

            save_json("case_types_delhi", case_types)
            t.passed = True
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_cause_list():
    """Test 4: Cause list PDFs with CAPTCHA (auto-retry)."""
    t = TestResult("Cause List PDFs (Delhi HC, civil)")
    try:
        from bharat_courts.captcha.ocr import OCRCaptchaSolver
        from bharat_courts.courts import get_court
        from bharat_courts.hcservices.client import HCServicesClient

        solver = OCRCaptchaSolver()
        async with HCServicesClient(captcha_solver=solver) as client:
            delhi = get_court("delhi")
            pdfs = await client.cause_list(delhi, civil=True)

            t.details["pdf_count"] = len(pdfs)
            if pdfs:
                first = pdfs[0]
                t.details["first_bench"] = first.bench[:60]
                t.details["first_type"] = first.cause_list_type
                t.details["has_pdf_url"] = bool(first.pdf_url)
                save_json(
                    "cause_list_delhi",
                    [p.to_dict(exclude_none=True) for p in pdfs],
                )
            t.passed = len(pdfs) > 0
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_case_status_by_party():
    """Test 5: Case status search by party name (auto-retry)."""
    t = TestResult("Case Status by Party (Delhi HC, 'state', 2024)")
    try:
        from bharat_courts.captcha.ocr import OCRCaptchaSolver
        from bharat_courts.courts import get_court
        from bharat_courts.hcservices.client import HCServicesClient

        solver = OCRCaptchaSolver()
        async with HCServicesClient(captcha_solver=solver) as client:
            delhi = get_court("delhi")
            cases = await client.case_status_by_party(
                delhi,
                party_name="state",
                year="2024",
            )

            t.details["cases_found"] = len(cases)
            if cases:
                first = cases[0]
                t.details["first_cnr"] = first.cnr_number
                t.details["first_petitioner"] = first.petitioner
                t.details["first_respondent"] = first.respondent
                save_json(
                    "case_status_party",
                    [c.to_dict(exclude_none=True) for c in cases[:10]],
                )
            t.passed = len(cases) > 0
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_case_status_by_number():
    """Test 6: Case status by case number (auto-retry)."""
    t = TestResult("Case Status by Number (Delhi HC, W.P.(C)/1/2024)")
    try:
        from bharat_courts.captcha.ocr import OCRCaptchaSolver
        from bharat_courts.courts import get_court
        from bharat_courts.hcservices.client import HCServicesClient

        solver = OCRCaptchaSolver()
        async with HCServicesClient(captcha_solver=solver) as client:
            delhi = get_court("delhi")
            cases = await client.case_status(
                delhi,
                case_type="134",  # W.P.(C)
                case_number="1",
                year="2024",
            )

            t.details["cases_found"] = len(cases)
            if cases:
                first = cases[0]
                t.details["first_cnr"] = first.cnr_number
                t.details["first_petitioner"] = first.petitioner
                save_json(
                    "case_status_number",
                    [c.to_dict(exclude_none=True) for c in cases[:10]],
                )
            t.passed = len(cases) > 0
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_json_serialization():
    """Test 7: JSON serialization of all model types."""
    t = TestResult("JSON Serialization")
    try:
        from bharat_courts.models import (
            CaseInfo,
            CaseOrder,
            CauseListPDF,
            Court,
            CourtType,
            JudgmentResult,
            SearchResult,
        )

        court = Court("Delhi HC", "delhi", "26", CourtType.HIGH_COURT)
        case = CaseInfo(
            case_number="1/2024",
            case_type="134",
            cnr_number="DLHC010000012024",
            petitioner="ABC Industries",
            respondent="State",
            court_name="Delhi HC",
            judges=["Justice A"],
            next_hearing_date=date(2026, 3, 1),
        )
        order = CaseOrder(order_date=date(2026, 1, 15), order_type="Order", judge="Justice B")
        judgment = JudgmentResult(
            title="ABC Industries v State",
            court_name="Delhi HC",
            judgment_date=date(2025, 12, 1),
            judges=["Justice C"],
        )
        cause_pdf = CauseListPDF(
            serial_number=1,
            bench="DIVISION BENCH - COURT NO. 1",
            cause_list_type="COMPLETE CAUSE LIST",
        )
        sr = SearchResult(items=[case], total_count=1, page=1)

        all_data = {
            "court": court.to_dict(),
            "case_info": case.to_dict(exclude_none=True),
            "case_order": order.to_dict(exclude_none=True),
            "judgment": judgment.to_dict(exclude_none=True),
            "cause_list_pdf": cause_pdf.to_dict(),
            "search_result": sr.to_dict(),
        }

        json_str = json.dumps(all_data, indent=2, ensure_ascii=False)
        t.details["json_length"] = len(json_str)
        save_json("model_serialization", all_data)

        parsed = json.loads(json_str)
        assert parsed["court"]["state_code"] == "26"
        assert parsed["case_info"]["cnr_number"] == "DLHC010000012024"
        assert parsed["case_info"]["next_hearing_date"] == "2026-03-01"
        assert parsed["search_result"]["total_pages"] == 1
        assert len(parsed["search_result"]["items"]) == 1

        t.passed = True
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_ocr_captcha_solver():
    """Test 8: OCR CAPTCHA solver stress test."""
    t = TestResult("OCR CAPTCHA Solver (5 fresh sessions)")
    try:
        import httpx

        from bharat_courts.captcha.ocr import OCRCaptchaSolver
        from bharat_courts.hcservices import endpoints

        solver = OCRCaptchaSolver()
        solved = []

        for _ in range(5):
            async with httpx.AsyncClient(
                timeout=30,
                verify=False,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                    )
                },
            ) as c:
                await c.get(endpoints.MAIN_PAGE_URL)
                resp = await c.get(endpoints.CAPTCHA_IMAGE_URL)
                result = await solver.solve(resp.content)
                solved.append(result)
            await asyncio.sleep(1)  # Rate limit

        t.details["solved_captchas"] = solved
        t.details["all_non_empty"] = all(len(s) > 0 for s in solved)
        t.details["all_reasonable_length"] = all(4 <= len(s) <= 8 for s in solved)
        t.passed = all(len(s) > 0 for s in solved)
    except Exception as e:
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


# --- Main ---


async def run_all():
    print("=" * 60)
    print("  bharat-courts — Comprehensive Live Test")
    print(f"  Date: {date.today().isoformat()}")
    print(f"  Results dir: {RESULTS_DIR}")
    print("=" * 60)
    print()

    test_funcs = [
        ("1/8", "Court Registry", test_court_registry),
        ("2/8", "Bench Listing", test_bench_listing),
        ("3/8", "Case Type Listing", test_case_type_listing),
        ("4/8", "Cause List", test_cause_list),
        ("5/8", "Case Status by Party", test_case_status_by_party),
        ("6/8", "Case Status by Number", test_case_status_by_number),
        ("7/8", "JSON Serialization", test_json_serialization),
        ("8/8", "OCR CAPTCHA Solver", test_ocr_captcha_solver),
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
