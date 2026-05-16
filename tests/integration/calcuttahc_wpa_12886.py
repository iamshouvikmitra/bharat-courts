#!/usr/bin/env python3
"""Test: Fetch WPA 12886/2024 (Sourav Roy Bhowmik vs Union of India) from Calcutta HC.

Tries multiple approaches:
1. HCServicesClient — case_status + court_orders
2. JudgmentSearchClient — keyword search (tests the CAPTCHA session fix)

Uses the default CAPTCHA solver (OCRCaptchaSolver / ddddocr) — no explicit
solver needed.
"""

import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


async def try_hcservices():
    """Approach 1: Look up case via HC Services portal."""
    from bharat_courts import HCServicesClient, get_court

    court = get_court("calcutta")

    async with HCServicesClient() as client:
        print("\n=== HC Services: Calcutta HC ===")
        benches = await client.list_benches(court)
        print(f"Benches: {benches}")

        # WPA is case_type=12 on Appellate Side (bench=3)
        case_types = await client.list_case_types(court, bench_code="3")
        wpa_types = {k: v for k, v in case_types.items() if "WPA" in v.upper()}
        print(f"WPA types on Appellate Side: {wpa_types}")

        # Try WPA (code 12) first — most likely match
        print("\n--- case_status: WPA 12886/2024, Appellate Side ---")
        cases = await client.case_status(
            court, case_type="12", case_number="12886", year="2024", bench_code="3"
        )

        if cases:
            print(f"Found {len(cases)} case(s)!")
            for c in cases:
                print(f"  Case: {c.case_number}")
                print(f"  CNR: {c.cnr_number}")
                print(f"  Petitioner: {c.petitioner}")
                print(f"  Respondent: {c.respondent}")
                print(f"  Status: {c.status}")
                print(f"  Reg Date: {c.registration_date}")
                print(f"  Judges: {c.judges}")

            # Fetch court orders
            print("\n--- court_orders ---")
            orders = await client.court_orders(
                court, case_type="12", case_number="12886", year="2024", bench_code="3"
            )
            if orders:
                print(f"Found {len(orders)} order(s)!")
                for i, order in enumerate(orders, 1):
                    print(f"  Order #{i}: {order.order_date} | {order.order_type} | {order.judge}")
                    if order.pdf_url:
                        print(f"    PDF: {order.pdf_url}")
                        pdf_data = await client.download_order_pdf(order.pdf_url)
                        path = f"/tmp/wpa_12886_2024_order_{i}.pdf"
                        with open(path, "wb") as f:
                            f.write(pdf_data)
                        print(f"    Saved: {path} ({len(pdf_data)} bytes)")
            else:
                print("No orders found.")
            return True
        else:
            print("No cases found.")
            return False


async def try_judgment_search():
    """Approach 2: Search via Judgment Search portal (tests CAPTCHA fix)."""
    from bharat_courts import JudgmentSearchClient

    async with JudgmentSearchClient() as client:
        print("\n=== Judgment Search ===")
        query = "Sourav Roy Bhowmik"
        print(f"Searching: '{query}'")
        result = await client.search(
            query, search_opt="ALL", court_type="2", max_captcha_attempts=5
        )
        print(f"Results: {result.total_count} total, {len(result.items)} on this page")

        for j in result.items:
            print(f"  - {j.title}")
            print(f"    Court: {j.court_name}, Date: {j.judgment_date}")
            if j.pdf_url:
                print(f"    PDF: {j.pdf_url}")

        if result.items:
            j = result.items[0]
            if j.pdf_url:
                j = await client.download_pdf(j)
                if j.pdf_bytes:
                    path = "/tmp/wpa_12886_2024_judgment.pdf"
                    with open(path, "wb") as f:
                        f.write(j.pdf_bytes)
                    print(f"\nSaved judgment: {path} ({len(j.pdf_bytes)} bytes)")
            return True

    return False


async def main():
    print("=" * 60)
    print("Test: WPA 12886/2024 — Sourav Roy Bhowmik vs Union of India")
    print("Court: Calcutta HC, Decided: 10-05-2024, CNR: WBCHCA0239512024")
    print("=" * 60)

    hc_ok = False
    try:
        hc_ok = await try_hcservices()
    except Exception as e:
        print(f"\nHC Services failed: {e}")

    js_ok = False
    try:
        js_ok = await try_judgment_search()
    except Exception as e:
        print(f"\nJudgment Search failed: {e}")

    print("\n" + "=" * 60)
    print(f"HC Services:     {'OK' if hc_ok else 'FAILED'}")
    print(f"Judgment Search: {'OK' if js_ok else 'FAILED'}")
    print("=" * 60)
    return 0 if (hc_ok or js_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
