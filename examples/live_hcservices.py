#!/usr/bin/env python3
"""Live example: query HC Services portal.

Usage:
    cd bharat-courts
    pip install -e ".[ocr]"
    python examples/live_hcservices.py                # Delhi HC, auto CAPTCHA
    python examples/live_hcservices.py bombay          # Bombay HC
    python examples/live_hcservices.py delhi bench     # just list benches (no CAPTCHA)

Demonstrates:
  - Bench listing (no CAPTCHA needed)
  - Case type listing (no CAPTCHA needed)
  - Cause list PDFs (CAPTCHA auto-solved with ddddocr)
  - Case status search (CAPTCHA auto-solved with ddddocr)
"""

import asyncio
import json
import sys

from bharat_courts.captcha.ocr import OCRCaptchaSolver
from bharat_courts.courts import get_court, list_high_courts
from bharat_courts.hcservices.client import HCServicesClient


async def list_benches_only(court_code: str):
    """List available benches — no CAPTCHA needed."""
    court = get_court(court_code)
    if not court:
        print(f"Unknown court: {court_code}")
        print(f"Available: {', '.join(c.code for c in list_high_courts())}")
        return

    solver = OCRCaptchaSolver()
    async with HCServicesClient(captcha_solver=solver) as client:
        benches = await client.list_benches(court)
        print(f"\nBenches for {court.name}:")
        for code, name in benches.items():
            print(f"  [{code}] {name}")

        case_types = await client.list_case_types(court)
        print(f"\nCase types ({len(case_types)} total):")
        for code, name in list(case_types.items())[:10]:
            print(f"  [{code}] {name}")
        if len(case_types) > 10:
            print(f"  ... and {len(case_types) - 10} more")


async def full_demo(court_code: str):
    """Full demo: benches, cause list, and case search."""
    court = get_court(court_code)
    if not court:
        print(f"Unknown court: {court_code}")
        return

    solver = OCRCaptchaSolver()
    async with HCServicesClient(captcha_solver=solver) as client:
        # 1. Benches
        print(f"[1/3] Listing benches for {court.name}...")
        benches = await client.list_benches(court)
        for code, name in benches.items():
            print(f"  [{code}] {name}")

        # 2. Cause list
        print("\n[2/3] Fetching cause list PDFs...")
        pdfs = await client.cause_list(court, civil=True)
        if pdfs:
            print(f"  {len(pdfs)} cause list PDFs:")
            for pdf in pdfs[:5]:
                print(f"    {pdf.bench[:60]}")
                print(f"    -> {pdf.pdf_url[:80]}")
        else:
            print("  No cause list available today")

        # 3. Case status by party name
        print("\n[3/3] Searching cases for 'state' (2024)...")
        cases = await client.case_status_by_party(court, party_name="state", year="2024")
        print(f"  Found {len(cases)} cases")
        for case in cases[:5]:
            print(f"  [{case.cnr_number}] {case.petitioner} v {case.respondent}")
        print("\n  All results as JSON:")
        if cases:
            print(json.dumps(cases[0].to_dict(exclude_none=True), indent=2))


def main():
    court_code = sys.argv[1] if len(sys.argv) > 1 else "delhi"
    mode = sys.argv[2] if len(sys.argv) > 2 else "full"

    print("=== bharat-courts HC Services Example ===\n")

    if mode == "bench":
        asyncio.run(list_benches_only(court_code))
    else:
        asyncio.run(full_demo(court_code))


if __name__ == "__main__":
    main()
