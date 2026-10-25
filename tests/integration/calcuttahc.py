#!/usr/bin/env python3
"""Live checks for the Calcutta High Court website client.

Covers ``CalcuttaHCClient`` (search_orders, download_order_pdf) against a
known-good regression case, cross-checks the same case through HC Services,
then searches a *different* WPA each day picked from a live HC Services party
search so the client is exercised beyond the one pinned case.

Usage::

    python tests/integration/calcuttahc.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import Check, Suite, first_working, require, rotate  # noqa: E402

require("ddddocr", "ocr")

suite = Suite(
    "Calcutta HC live checks",
    results_dir="/tmp/bharat_courts_calcuttahc_test",
    backend="calcuttahc",
)

# WPA 12886/2024 — Sourav Roy Bhowmik vs Union of India, decided 10-05-2024.
KNOWN = {"case_type": "12", "case_number": "12886", "year": "2024", "cnr": "WBCHCA0239512024"}
APPELLATE_BENCH = "3"  # HC Services bench code for the Appellate Side
WPA_CODE = "12"  # case type on calcuttahighcourt.gov.in
LAST_YEAR = str(date.today().year - 1)
PARTIES = ["union of india", "state of west bengal", "bank"]
shared: dict = {}


@suite.check("Regression: WPA 12886/2024 orders", "CalcuttaHCClient.search_orders")
async def check_known_case(c: Check) -> None:
    from bharat_courts import CalcuttaHCClient

    async with CalcuttaHCClient() as client:
        info, orders = await client.search_orders(
            case_type=KNOWN["case_type"], case_number=KNOWN["case_number"], year=KNOWN["year"]
        )
    assert info is not None, "no case metadata returned"
    c.details["cnr"] = info.cnr_number
    c.details["parties"] = f"{info.petitioner[:30]} vs {info.respondent[:30]}"
    c.details["orders"] = len(orders)
    assert info.cnr_number == KNOWN["cnr"], f"CNR mismatch: {info.cnr_number}"
    assert orders, "known decided case returned no orders"
    first = orders[0]
    c.details["first_order"] = f"{first.order_date} {first.order_type} {first.judge[:30]}"
    assert any(o.pdf_url for o in orders), "no order carries a resolved PDF URL"
    shared["orders"] = orders
    suite.save_json("wpa_12886_2024", [o.to_dict(exclude_none=True) for o in orders])
    c.passed = True


@suite.check("Order PDF download", "CalcuttaHCClient.download_order_pdf")
async def check_pdf(c: Check) -> None:
    from bharat_courts import CalcuttaHCClient

    orders = [o for o in shared.get("orders", []) if o.pdf_url]
    assert orders, "no order with a PDF URL"
    async with CalcuttaHCClient() as client:
        data = await client.download_order_pdf(orders[0].pdf_url)
    c.details["size"] = f"{len(data):,} bytes"
    assert data[:4] == b"%PDF"
    c.passed = True


@suite.check("Cross-check via HC Services (same case)", "HCServicesClient.case_status(bench_code)")
async def check_hcservices_crosscheck(c: Check) -> None:
    from bharat_courts import HCServicesClient, get_court

    court = get_court("calcutta")
    async with HCServicesClient() as client:
        cases = await client.case_status(
            court,
            case_type=KNOWN["case_type"],
            case_number=KNOWN["case_number"],
            year=KNOWN["year"],
            bench_code=APPELLATE_BENCH,
        )
    c.details["cases"] = len(cases)
    assert cases, "HC Services found no case"
    c.details["cnr"] = cases[0].cnr_number
    assert cases[0].cnr_number == KNOWN["cnr"], "HC Services and website disagree on the CNR"
    c.passed = True


@suite.check("Rotating WPA from a live party search", "CalcuttaHCClient.search_orders(rotating)")
async def check_rotating_case(c: Check) -> None:
    from bharat_courts import CalcuttaHCClient, HCServicesClient, get_court

    court = get_court("calcutta")
    async with HCServicesClient() as hc:

        async def party_search(party: str):
            rows = await hc.case_status_by_party(
                court, party_name=party, year=LAST_YEAR, bench_code=APPELLATE_BENCH
            )
            return [
                r
                for r in rows
                if r.case_type.upper().startswith("WPA")
                and r.cnr_number.startswith("WBCHCA")
                and r.registration_number
            ]

        party, rows = await first_working(c, rotate(PARTIES), party_search, label="party")
    assert rows, "no WPA rows from any party search"
    c.details["wpa_rows"] = len(rows)
    candidates = rotate(rows, 3)

    async with CalcuttaHCClient() as client:

        async def lookup(row):
            year = row.case_number.split("/")[-1] if "/" in row.case_number else LAST_YEAR
            info, orders = await client.search_orders(
                case_type=WPA_CODE, case_number=row.registration_number, year=year
            )
            return (row, info, orders)

        hit, value = await first_working(
            c,
            candidates,
            lookup,
            label="lookup",
            key=lambda r: f"WPA/{r.registration_number}",
            accept=lambda v: v[1] is not None and v[1].cnr_number == v[0].cnr_number,
        )
    assert hit is not None, "website returned no matching case for any sampled WPA"
    _, info, orders = value
    c.details["case"] = f"{info.case_number} cnr={info.cnr_number} orders={len(orders)}"
    c.passed = True


if __name__ == "__main__":
    suite.main()
