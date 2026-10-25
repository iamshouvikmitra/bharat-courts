#!/usr/bin/env python3
"""Live checks for the HC Services portal (hcservices.ecourts.gov.in).

Covers ``HCServicesClient`` end to end — bench / case-type listings, cause
lists, party search, case-number search, CNR case detail, court orders, order
PDF download, advocate search — plus the court registry, model serialization
and the OCR CAPTCHA solver.

Courts rotate daily over ``HC_POOL`` (see ``_common.rotate``) and every live
check falls through to the next court when one has no data, so one court
going dark (Delhi stopped publishing cause lists here in Oct 2026) is reported
in the details without failing the backend. Later checks chain off earlier
results: the party search feeds the case-number, CNR, orders and advocate
checks, so nothing is pinned to a hand-picked case.

Usage::

    python tests/integration/hcservices.py
    E2E_SEED=3 python tests/integration/hcservices.py   # reproduce a rotation
"""

from __future__ import annotations

import asyncio
import json
import re
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
    "HC Services live checks", results_dir="/tmp/bharat_courts_test", backend="hcservices"
)

# Principal benches only (bench_code "1"); bench variants are covered by the
# bench listing check. Order is irrelevant — rotation picks the start.
HC_POOL = [
    "delhi",
    "bombay",
    "allahabad",
    "karnataka",
    "madras",
    "gujarat",
    "kerala",
    "mp",
    "punjab",
    "rajasthan",
    "telangana",
    "patna",
    "orissa",
    "calcutta",
    "gauhati",
    "chhattisgarh",
    "jharkhand",
    "himachal",
    "uttarakhand",
    "andhra",
]
COURTS = rotate(HC_POOL)
LAST_YEAR = str(date.today().year - 1)
PARTIES = ["union of india", "state"]
shared: dict = {}


def _client():
    from bharat_courts.captcha.ocr import OCRCaptchaSolver
    from bharat_courts.hcservices.client import HCServicesClient

    return HCServicesClient(captcha_solver=OCRCaptchaSolver())


def _court(code: str):
    from bharat_courts.courts import get_court

    court = get_court(code)
    assert court is not None, f"unknown court {code!r}"
    return court


def _resolve_case_type_code(case_types: dict[str, str], label: str) -> str | None:
    """Map a search-row label like ``W.P.(C)`` to the portal's numeric code.

    ``list_case_types`` names look like ``W.P.(C)(WRIT PETITION (CIVIL))-134``:
    abbreviation, full name in brackets, ``-code``. Match the abbreviation.
    """
    want = label.strip().upper()
    if not want:
        return None
    for code, name in case_types.items():
        abbrev = name.split("(", 1)[0].strip().upper()
        if abbrev == want:
            return code
    for code, name in case_types.items():
        if name.upper().startswith(want):
            return code
    return None


def _year_of(case) -> str:
    return case.case_number.split("/")[-1] if "/" in case.case_number else LAST_YEAR


# ---------------------------------------------------------------------------
# offline
# ---------------------------------------------------------------------------


@suite.check("Court registry", "get_court", "list_high_courts", "infer_court_from_cnr")
def check_registry(c: Check) -> None:
    from bharat_courts.courts import (
        get_court,
        get_court_by_state_code,
        infer_court_from_cnr,
        list_all_courts,
        list_high_courts,
    )

    c.details["total_courts"] = len(list_all_courts())
    c.details["high_courts"] = len(list_high_courts())
    missing = [code for code in HC_POOL if get_court(code) is None]
    assert not missing, f"pool entries not in registry: {missing}"
    assert get_court("delhi").state_code == "26"
    assert get_court_by_state_code("26").code == "delhi"
    routed = {
        "DLHC010230802020": "delhi",
        "HCBM010000012020": "bombay",
        "WBCHCA0239512024": "calcutta",
        "HBHC010000012020": "telangana",
        "ESCR010000301950": "sci",
    }
    for cnr, want in routed.items():
        got = infer_court_from_cnr(cnr)
        assert got is not None and got.code == want, f"{cnr} → {got and got.code}, want {want}"
    c.details["cnr_routing"] = f"{len(routed)} prefixes OK"
    c.details["today's rotation"] = ", ".join(COURTS[:4]) + ", …"
    c.passed = True


# ---------------------------------------------------------------------------
# no-CAPTCHA listings
# ---------------------------------------------------------------------------


@suite.check("Bench listing (3 rotating courts)", "HCServicesClient.list_benches")
async def check_benches(c: Check) -> None:
    async with _client() as client:
        for code in COURTS[:3]:
            benches = await client.list_benches(_court(code))
            c.details[code] = benches
            assert benches, f"no benches for {code}"
    c.passed = True


@suite.check("Case type listing", "HCServicesClient.list_case_types", "parse_code_name_list")
async def check_case_types(c: Check) -> None:
    async with _client() as client:

        async def run(code: str):
            return await client.list_case_types(_court(code))

        code, case_types = await first_working(
            c, COURTS, run, label="types", accept=lambda d: len(d) > 10, max_tries=3
        )
    assert case_types, "no court returned a usable case-type list"
    c.details["court"] = code
    c.details["sample"] = dict(list(case_types.items())[:3])
    shared["case_types"] = {code: case_types}
    suite.save_json(f"case_types_{code}", case_types)
    c.passed = True


# ---------------------------------------------------------------------------
# CAPTCHA-gated
# ---------------------------------------------------------------------------


@suite.check("Cause list PDFs (rotating courts × working days)", "HCServicesClient.cause_list")
async def check_cause_list(c: Check) -> None:
    dates = working_day_candidates(back=1, forward=1)[1:]  # skip "today": often a holiday
    candidates = [(code, d) for code in COURTS[:4] for d in dates]
    async with _client() as client:

        async def run(cand):
            code, d = cand
            return await client.cause_list(_court(code), civil=True, causelist_date=ddmmyyyy(d))

        hit, pdfs = await first_working(
            c, candidates, run, label="pdfs", key=lambda t: f"{t[0]} {ddmmyyyy(t[1])}"
        )
    assert pdfs, "no court in today's rotation published a cause list"
    code, d = hit
    first = pdfs[0]
    c.details["court"] = f"{code} {ddmmyyyy(d)}: {len(pdfs)} PDFs"
    c.details["first"] = f"{first.bench[:50]} | {first.cause_list_type} | url={bool(first.pdf_url)}"
    assert first.pdf_url, "cause list row has no PDF URL"
    suite.save_json(f"cause_list_{code}", [p.to_dict(exclude_none=True) for p in pdfs])
    c.passed = True


@suite.check("Case status by party (rotating court)", "HCServicesClient.case_status_by_party")
async def check_party(c: Check) -> None:
    from bharat_courts.hcservices.parser import dedupe_by_cnr

    candidates = [(code, p) for code in COURTS[:2] for p in PARTIES]
    async with _client() as client:

        async def run(cand):
            code, party = cand
            return await client.case_status_by_party(_court(code), party_name=party, year=LAST_YEAR)

        hit, cases = await first_working(
            c, candidates, run, label="cases", key=lambda t: " / ".join(t)
        )
    assert cases, "no party search returned rows on any rotated court"
    code, party = hit
    unique = dedupe_by_cnr(cases)
    first = unique[0]
    c.details["court"] = f"{code} ({party!r}, {LAST_YEAR})"
    c.details["rows / unique"] = f"{len(cases)} / {len(unique)}"
    c.details["first"] = (
        f"{first.case_type} {first.case_number} {first.cnr_number} — {first.petitioner[:40]}"
    )
    assert first.cnr_number and first.case_number, "row missing CNR / case number"
    shared["court"] = code
    shared["cases"] = unique
    suite.save_json("case_status_party", [x.to_dict(exclude_none=True) for x in unique[:10]])
    c.passed = True


def _own_cases():
    """Rows whose CNR belongs to the searched court (HC rows may carry a trial court's)."""
    from bharat_courts.courts import infer_court_from_cnr

    code = shared.get("court")
    rows = shared.get("cases") or []
    own = []
    for r in rows:
        court = infer_court_from_cnr(r.cnr_number)
        if court is not None and court.code == code:
            own.append(r)
    assert own, "no party-search rows to chain from (party check failed?)"
    return code, rotate(own, 6)


@suite.check(
    "Case detail by CNR (chained)", "HCServicesClient.case_status_by_cnr", "parse_case_detail"
)
async def check_cnr_detail(c: Check) -> None:
    code, rows = _own_cases()
    async with _client() as client:

        async def run(row):
            return await client.case_status_by_cnr(row.cnr_number)

        row, detail = await first_working(
            c,
            rows,
            run,
            label="detail",
            key=lambda r: r.cnr_number,
            accept=lambda d: bool(d.petitioners or d.respondents or d.history or d.status),
            max_tries=3,
        )
    assert detail is not None, "no CNR lookup returned a populated case page"
    c.details["cnr"] = detail.cnr_number
    c.details["status / stage"] = f"{detail.status!r} / {detail.case_stage!r}"
    c.details["parties"] = f"{len(detail.petitioners)} pet, {len(detail.respondents)} res"
    c.details["history / orders / acts"] = (
        f"{len(detail.history)} / {len(detail.orders)} / {len(detail.acts)}"
    )
    assert detail.cnr_number == row.cnr_number
    assert detail.to_json(), "CaseDetail.to_json failed"
    shared["detail"] = detail
    suite.save_json("case_detail", detail.to_dict(exclude_none=True))
    c.passed = True


@suite.check("Case status by number (chained)", "HCServicesClient.case_status")
async def check_by_number(c: Check) -> None:
    code, rows = _own_cases()
    async with _client() as client:
        case_types = shared.get("case_types", {}).get(code)
        if case_types is None:
            case_types = await client.list_case_types(_court(code))
            shared.setdefault("case_types", {})[code] = case_types

        async def run(row):
            type_code = _resolve_case_type_code(case_types, row.case_type)
            if type_code is None:
                raise LookupError(f"case type {row.case_type!r} not in list_case_types")
            found = await client.case_status(
                _court(code),
                case_type=type_code,
                case_number=row.registration_number,
                year=_year_of(row),
            )
            return (type_code, found, row)

        row, value = await first_working(
            c,
            rows,
            run,
            label="lookup",
            key=lambda r: f"{r.case_type}/{r.registration_number}/{_year_of(r)}",
            accept=lambda v: any(x.cnr_number == v[2].cnr_number for x in v[1]),
            max_tries=3,
        )
    assert value is not None, "no case-number lookup returned the searched case"
    type_code, found, _ = value
    c.details["query"] = (
        f"{code} type={type_code} no={row.registration_number} year={_year_of(row)}"
    )
    c.details["found"] = len(found)
    shared["number_hit"] = (code, type_code, row)
    c.passed = True


@suite.check(
    "Court orders + order PDF (chained)", "HCServicesClient.court_orders", "download_order_pdf"
)
async def check_orders(c: Check) -> None:
    code, rows = _own_cases()
    hit = shared.get("number_hit")
    async with _client() as client:
        case_types = shared.get("case_types", {}).get(code) or await client.list_case_types(
            _court(code)
        )
        ordered = ([hit[2]] + [r for r in rows if r is not hit[2]]) if hit else rows

        async def fetch_orders(row):
            type_code = _resolve_case_type_code(case_types, row.case_type)
            if type_code is None:
                raise LookupError(f"case type {row.case_type!r} not resolvable")
            return await client.court_orders(
                _court(code),
                case_type=type_code,
                case_number=row.registration_number,
                year=_year_of(row),
            )

        row, orders = await first_working(
            c,
            ordered,
            fetch_orders,
            label="orders",
            key=lambda r: f"{r.case_type}/{r.registration_number}",
            max_tries=4,
        )
        assert orders, "none of the sampled cases returned any order"
        c.details["case"] = f"{row.case_type} {row.case_number} ({row.cnr_number})"
        c.details["first_order"] = f"{orders[0].order_date} {orders[0].order_type}"
        suite.save_json("court_orders", [o.to_dict(exclude_none=True) for o in orders])

        # Oldest first: an order uploaded today is often not on the file
        # server yet and comes back as the portal's "Unable to connect" page.
        with_pdf = sorted((o for o in orders if o.pdf_url), key=lambda o: o.order_date)
        assert with_pdf, "no order carries a PDF URL"

        async def fetch_pdf(order):
            return await client.download_order_pdf(order.pdf_url)

        order, data = await first_working(
            c,
            with_pdf,
            fetch_pdf,
            label="pdf",
            key=lambda o: str(o.order_date),
            accept=lambda d: d[:4] == b"%PDF",
            max_tries=3,
        )
    if data is None:
        if c.skip_if_portal_outage("display_pdf"):
            return
        raise AssertionError("no order PDF could be downloaded")
    c.details["pdf"] = f"{order.order_date}: {len(data):,} bytes"
    c.passed = True


@suite.check("Advocate search (chained from case detail)", "HCServicesClient.advocate_search")
async def check_advocate(c: Check) -> None:
    detail = shared.get("detail")
    code = shared.get("court")
    assert detail is not None and code, "no case detail to take an advocate from"
    names: list[str] = []
    for p in detail.petitioners + detail.respondents:
        # The page joins several advocates with commas ("N J DUTTA,B AHMED")
        # and may suffix a bar code in brackets; search wants one bare name.
        for raw in re.sub(r"\(.*?\)", "", p.advocate or "").split(","):
            name = re.sub(r"^(MR|MS|MRS|DR|SHRI|SMT)\.?\s+", "", raw.strip(), flags=re.I)
            if len(name) >= 5 and " " in name and name not in names:
                names.append(name)
    c.details["advocates_on_case"] = names[:3]
    assert names, "case detail lists no advocate names"
    async with _client() as client:

        async def run(name: str):
            return await client.advocate_search(_court(code), advocate_name=name)

        name, result = await first_working(
            c, names, run, label="search", accept=lambda r: bool(r.cases), max_tries=3
        )
    assert result is not None, "advocate search returned no cases for any advocate on the case"
    c.details["matched"] = (
        f"{result.name or result.raw_name} code={result.code!r} total={result.total_records}"
    )
    c.details["cases"] = len(result.cases)
    c.passed = True


# ---------------------------------------------------------------------------
# models + solver
# ---------------------------------------------------------------------------


@suite.check("Model JSON round-trip", "_Serializable.to_dict", "to_json")
def check_serialization(c: Check) -> None:
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
        case_type="W.P.(C)",
        cnr_number="DLHC010000012024",
        petitioner="ABC Industries",
        respondent="State",
        judges=["Justice A"],
        next_hearing_date=date(2026, 3, 1),
    )
    payload = {
        "court": court.to_dict(),
        "case_info": case.to_dict(exclude_none=True),
        "case_order": CaseOrder(order_date=date(2026, 1, 15), order_type="Order").to_dict(
            exclude_none=True
        ),
        "judgment": JudgmentResult(title="ABC v State", court_name="Delhi HC").to_dict(
            exclude_none=True
        ),
        "cause_list_pdf": CauseListPDF(serial_number=1, bench="DB-I").to_dict(),
        "search_result": SearchResult(items=[case], total_count=1, page=1).to_dict(),
    }
    parsed = json.loads(json.dumps(payload))
    assert parsed["court"]["state_code"] == "26"
    assert parsed["case_info"]["next_hearing_date"] == "2026-03-01"
    assert parsed["search_result"]["total_pages"] == 1
    if shared.get("detail") is not None:
        assert json.loads(shared["detail"].to_json())["cnr_number"]
        c.details["live CaseDetail"] = "round-trips"
    c.details["keys"] = list(payload)
    c.passed = True


@suite.check("OCR CAPTCHA solver (4 fresh sessions)", "OCRCaptchaSolver.solve")
async def check_ocr(c: Check) -> None:
    import httpx

    from bharat_courts.captcha.ocr import OCRCaptchaSolver
    from bharat_courts.config import config
    from bharat_courts.hcservices import endpoints

    solver = OCRCaptchaSolver()
    solved: list[str] = []
    blips = 0
    transient = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
    for _ in range(4):
        try:
            async with httpx.AsyncClient(
                timeout=30,
                verify=False,
                follow_redirects=True,
                proxy=config.proxy or None,
                headers={"User-Agent": config.user_agent},
            ) as http:
                await http.get(endpoints.MAIN_PAGE_URL)
                resp = await http.get(endpoints.CAPTCHA_IMAGE_URL)
                solved.append(await solver.solve(resp.content))
        except transient:
            blips += 1  # connectivity, not OCR quality
        await asyncio.sleep(1)
    non_empty = [s for s in solved if s]
    c.details["solved"] = solved
    c.details["fetched"] = f"{len(solved)}/4 ({blips} transport blip(s))"
    c.details["plausible_length"] = all(4 <= len(s) <= 8 for s in non_empty)
    # ddddocr is probabilistic; the CAPTCHA-gated checks above already prove
    # real solves. Only judge the solver when we fetched >= 2 images.
    c.passed = len(solved) < 2 or len(non_empty) >= (len(solved) + 1) // 2


if __name__ == "__main__":
    suite.main()
