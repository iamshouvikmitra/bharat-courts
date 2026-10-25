#!/usr/bin/env python3
"""Live checks for the District Courts portal (services.ecourts.gov.in).

Covers ``DistrictCourtClient`` end to end: the state → district → complex →
establishment → case-type cascade (no CAPTCHA), cause-list court discovery and
cause lists, party search, CNR case detail and court orders (CAPTCHA). The
state rotates daily over ``STATE_POOL``; the district is the state's main
city when the live list has it, so a different establishment is exercised
each day and one dead district cannot fail the backend.

Usage::

    python tests/integration/districtcourts.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import (  # noqa: E402
    Check,
    Suite,
    ddmmyyyy,
    first_working,
    require,
    rotate,
    working_day_candidates,
)

require("ddddocr", "ocr")

suite = Suite(
    "District Courts live checks",
    results_dir="/tmp/bharat_courts_district_test",
    backend="districtcourts",
)

# (state_code, state name, preferred district names — the state's big cities)
STATE_POOL = [
    ("8", "Bihar", ["Patna"]),
    ("26", "Delhi", ["New Delhi", "Central", "South", "Tis Hazari"]),
    ("1", "Maharashtra", ["Pune", "Mumbai", "Nagpur"]),
    ("3", "Karnataka", ["Bengaluru", "Bangalore", "Mysuru"]),
    ("13", "Uttar Pradesh", ["Lucknow", "Kanpur", "Varanasi"]),
    ("10", "Tamil Nadu", ["Chennai", "Coimbatore", "Madurai"]),
    ("17", "Gujarat", ["Ahmedabad", "Surat", "Vadodara"]),
    ("4", "Kerala", ["Ernakulam", "Thiruvananthapuram"]),
    ("23", "Madhya Pradesh", ["Bhopal", "Indore", "Jabalpur"]),
    ("9", "Rajasthan", ["Jaipur", "Jodhpur"]),
    ("16", "West Bengal", ["Kolkata", "Howrah", "Alipore"]),
    ("29", "Telangana", ["Hyderabad", "Ranga Reddy"]),
]
STATES = rotate(STATE_POOL)
LAST_YEAR = str(date.today().year - 1)
# Specific parties, not generic words: an over-broad term matches tens of
# thousands of rows and the portal times out generating them.
PARTIES = ["Union of India", "State Bank of India", "Insurance Company"]
shared: dict = {}


def _client():
    from bharat_courts.captcha.ocr import OCRCaptchaSolver
    from bharat_courts.districtcourts.client import DistrictCourtClient

    return DistrictCourtClient(captcha_solver=OCRCaptchaSolver())


def _pick_district(districts: dict[str, str], preferred: list[str]) -> tuple[str, str]:
    for want in preferred:
        for code, name in districts.items():
            if want.lower() in name.lower():
                return code, name
    code, name = sorted(districts.items(), key=lambda kv: kv[1])[0]
    return code, name


def _loc() -> tuple[str, str]:
    assert "state" in shared and "dist" in shared, "no district selected (cascade check failed?)"
    return shared["state"], shared["dist"]


def _complex() -> tuple[str, str]:
    assert "complex" in shared, "no complex selected (complex check failed?)"
    return shared["complex"], shared.get("est", "")


# ---------------------------------------------------------------------------
# cascade (no CAPTCHA)
# ---------------------------------------------------------------------------


@suite.check("States (live + snapshot drift)", "DistrictCourtClient.list_states", "DISTRICT_STATES")
async def check_states(c: Check) -> None:
    from bharat_courts.districtcourts.endpoints import DISTRICT_STATES

    async with _client() as client:
        live = await client.list_states()
    c.details["total_states"] = len(live)
    assert len(live) >= 36, f"too few states: {len(live)}"
    assert live.get("26") == "Delhi" and live.get("8") == "Bihar"
    snapshot = {v: k for k, v in DISTRICT_STATES.items()}
    drift = {
        code: (name, snapshot.get(code))
        for code, name in live.items()
        if snapshot.get(code) != name
    }
    c.details["drift"] = drift or "none"
    assert not drift, f"DISTRICT_STATES snapshot has drifted from the live portal: {drift}"
    c.details["today's rotation"] = ", ".join(s[1] for s in STATES[:3]) + ", …"
    c.passed = True


@suite.check("Districts (rotating state)", "DistrictCourtClient.list_districts")
async def check_districts(c: Check) -> None:
    async with _client() as client:

        async def run(entry):
            return await client.list_districts(entry[0])

        entry, districts = await first_working(
            c,
            STATES,
            run,
            label="districts",
            key=lambda e: e[1],
            accept=lambda d: len(d) > 3,
            max_tries=3,
        )
    assert districts, "no state returned a district list"
    state_code, state_name, preferred = entry
    dist_code, dist_name = _pick_district(districts, preferred)
    shared.update(state=state_code, state_name=state_name, dist=dist_code, dist_name=dist_name)
    c.details["chosen"] = f"{state_name} ({state_code}) / {dist_name} ({dist_code})"
    suite.save_json(f"districts_{state_code}", districts)
    c.passed = True


@suite.check("Court complexes", "DistrictCourtClient.list_complexes", "parse_complex_value")
async def check_complexes(c: Check) -> None:
    from bharat_courts.districtcourts.parser import parse_complex_value

    state, dist = _loc()
    async with _client() as client:
        complexes = await client.list_complexes(state, dist)
    c.details["complex_count"] = len(complexes)
    assert complexes, "no court complexes"
    parsed = [(parse_complex_value(v), name) for v, name in complexes.items()]
    # Prefer the complex with the most establishments: biggest docket, and it
    # exercises the establishment branch of the cascade.
    parsed.sort(key=lambda p: len(p[0][1]), reverse=True)
    (code, ests, needs_est), name = parsed[0]
    shared.update(complex=code, complex_name=name, ests=ests, needs_est=needs_est)
    shared["complexes"] = [(p[0][0], p[0][1], p[0][2], p[1]) for p in parsed]
    c.details["chosen"] = f"{name} code={code} ests={ests} needs_establishment={needs_est}"
    suite.save_json(f"complexes_{state}_{dist}", complexes)
    c.passed = True


@suite.check("Establishments", "DistrictCourtClient.list_establishments")
async def check_establishments(c: Check) -> None:
    state, dist = _loc()
    with_est = [x for x in shared.get("complexes", []) if x[2]]
    if not with_est:
        c.details["note"] = "no complex in this district needs an establishment — nothing to list"
        c.passed = True
        return
    code, ests, _, name = with_est[0]
    async with _client() as client:
        listed = await client.list_establishments(state, dist, code)
    c.details["complex"] = name
    c.details["establishments"] = listed
    assert listed, "complex flagged as needing an establishment but none listed"
    if code == shared.get("complex"):
        shared["est"] = next(iter(listed))
    c.passed = True


@suite.check("Case types", "DistrictCourtClient.list_case_types")
async def check_case_types(c: Check) -> None:
    state, dist = _loc()
    complex_code, est = _complex()
    if shared.get("needs_est") and not est:
        est = shared["ests"][0] if shared.get("ests") else ""
        shared["est"] = est
    async with _client() as client:
        case_types = await client.list_case_types(state, dist, complex_code, est)
    c.details["count"] = len(case_types)
    c.details["sample"] = dict(list(case_types.items())[:3])
    assert case_types, "no case types"
    shared["case_types"] = case_types
    c.passed = True


# ---------------------------------------------------------------------------
# CAPTCHA-gated
# ---------------------------------------------------------------------------


@suite.check(
    "Cause-list courts + cause list", "list_cause_list_courts", "DistrictCourtClient.cause_list"
)
async def check_cause_list(c: Check) -> None:
    state, dist = _loc()
    complex_code, est = _complex()
    dates = working_day_candidates(back=1, forward=1)
    async with _client() as client:
        courts = await client.list_cause_list_courts(state, dist, complex_code, est)
        c.details["courts"] = len(courts)
        assert courts, "no courts offered for cause lists"
        court_no, court_name = next(iter(courts.items()))
        c.details["court"] = f"{court_name[:50]} ({court_no})"

        async def run(d):
            return await client.cause_list(
                state_code=state,
                dist_code=dist,
                court_complex_code=complex_code,
                est_code=est,
                court_no=court_no,
                court_name=court_name,
                causelist_date=ddmmyyyy(d),
            )

        # An empty board is a legitimate answer (holiday, small court); a
        # parser break raises. So accept any list, and only keep going while
        # the portal errors.
        d, entries = await first_working(
            c, dates, run, label="entries", key=ddmmyyyy, accept=lambda e: e is not None
        )
    if entries is None:
        if c.skip_if_portal_outage("cause_list/submitCauseList"):
            return
        raise AssertionError("cause_list failed on every candidate day")
    if entries:
        first = entries[0]
        c.details["first"] = f"#{first.serial_number} {first.case_number} {first.petitioner[:30]}"
    else:
        c.details["note"] = "board empty on the sampled day (valid)"
    c.passed = True


@suite.check("Case status by party (rotating complex)", "DistrictCourtClient.case_status_by_party")
async def check_party(c: Check) -> None:
    state, dist = _loc()
    top = shared.get("complexes", [])[:2]
    candidates = [(cx, party) for cx in top for party in PARTIES]
    async with _client() as client:

        async def run(cand):
            (code, ests, needs, _name), party = cand
            est = (
                shared.get("est") if code == shared.get("complex") else (ests[0] if needs else "")
            ) or ""
            rows = await client.case_status_by_party(
                state_code=state,
                dist_code=dist,
                court_complex_code=code,
                est_code=est,
                party_name=party,
                year=LAST_YEAR,
            )
            return (code, est, rows)

        hit, value = await first_working(
            c,
            candidates,
            run,
            label="rows",
            key=lambda t: f"{t[0][3][:25]} / {t[1]}",
            accept=lambda v: bool(v[2]),
        )
    assert value is not None, "no party search returned rows on any complex"
    code, est, rows = value
    first = rows[0]
    c.details["found"] = len(rows)
    c.details["first"] = (
        f"{first.case_number} {first.cnr_number} — "
        f"{first.petitioner[:30]} vs {first.respondent[:30]}"
    )
    assert first.case_number, "row missing case number"
    shared.update(cases=rows, case_complex=code, case_est=est)
    suite.save_json("case_status_party", [r.to_dict(exclude_none=True) for r in rows[:10]])
    c.passed = True


@suite.check(
    "Case detail by CNR (chained)", "DistrictCourtClient.case_status_by_cnr", "parse_case_detail"
)
async def check_cnr_detail(c: Check) -> None:
    rows = [r for r in shared.get("cases", []) if r.cnr_number]
    assert rows, "no party-search rows with a CNR to chain from"
    async with _client() as client:

        async def run(row):
            return await client.case_status_by_cnr(row.cnr_number)

        row, detail = await first_working(
            c,
            rotate(rows, 4),
            run,
            label="detail",
            key=lambda r: r.cnr_number,
            accept=lambda d: bool(d.petitioners or d.respondents or d.history or d.case_stage),
            max_tries=3,
        )
    assert detail is not None, "no CNR lookup returned a populated case page"
    c.details["cnr"] = detail.cnr_number
    c.details["stage / status"] = f"{detail.case_stage!r} / {detail.status!r}"
    c.details["court"] = detail.court_number_and_judge[:60]
    c.details["parties / history / orders"] = (
        f"{len(detail.petitioners)}+{len(detail.respondents)} / "
        f"{len(detail.history)} / {len(detail.orders)}"
    )
    assert detail.cnr_number == row.cnr_number
    suite.save_json("case_detail", detail.to_dict(exclude_none=True))
    c.passed = True


@suite.check("Court orders by case number (chained)", "DistrictCourtClient.court_orders")
async def check_orders(c: Check) -> None:
    state, dist = _loc()
    rows = shared.get("cases") or []
    complex_code = shared.get("case_complex")
    est = shared.get("case_est", "")
    assert rows and complex_code, "no rows / complex to chain from"
    async with _client() as client:
        case_types = await client.list_case_types(state, dist, complex_code, est)
        by_label = {name.split("-")[0].strip().upper(): code for code, name in case_types.items()}

        async def run(row):
            label = row.case_type.strip().upper()
            code = by_label.get(label) or next(
                (cd for cd, nm in case_types.items() if nm.upper().startswith(label)), None
            )
            if code is None:
                raise LookupError(f"case type {row.case_type!r} not in list_case_types")
            parts = row.case_number.split("/")
            number, year = (parts[1], parts[2]) if len(parts) >= 3 else (parts[-1], LAST_YEAR)
            orders = await client.court_orders(
                state_code=state,
                dist_code=dist,
                court_complex_code=complex_code,
                est_code=est,
                case_type=code,
                case_number=number,
                year=year,
            )
            return orders

        row, orders = await first_working(
            c,
            rotate(rows, 5),
            run,
            label="orders",
            key=lambda r: r.case_number,
            accept=lambda o: o is not None,  # an empty order list is a valid answer
            max_tries=3,
        )
    if orders is None:
        if c.skip_if_portal_outage("courtorder/submitCaseNo"):
            return
        raise AssertionError("court_orders failed for every sampled case")
    c.details["case"] = row.case_number
    c.details["orders"] = len(orders)
    if orders:
        c.details["first"] = (
            f"{orders[0].order_date} {orders[0].order_type} pdf={bool(orders[0].pdf_url)}"
        )
    c.passed = True


if __name__ == "__main__":
    suite.main()
