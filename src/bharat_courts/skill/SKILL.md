---
name: bharat-courts
description: Access Indian court data — search cases, download orders, and get cause lists from eCourts High Courts, District Courts, and the Supreme Court. Use when the user needs to look up Indian court cases, search by party name, get court orders or judgments, or access daily cause lists.
---

# Indian Court Data with bharat-courts

Async Python SDK for accessing Indian court data from eCourts portals.

## Installation

```bash
pip install bharat-courts[ocr]   # with automatic CAPTCHA solving
```

## Quick Start — High Courts

```python
import asyncio
from bharat_courts import get_court, HCServicesClient
from bharat_courts.captcha.ocr import OCRCaptchaSolver

async def main():
    court = get_court("delhi")  # or "bombay", "calcutta", etc.
    solver = OCRCaptchaSolver()

    async with HCServicesClient(captcha_solver=solver) as client:
        # Search by party name
        cases = await client.case_status_by_party(court, party_name="state", year="2024")

        # Search by case number
        cases = await client.case_status(court, case_type="134", case_number="1", year="2024")

        # Get cause list PDFs
        pdfs = await client.cause_list(court, civil=True)

        # Get court orders
        orders = await client.court_orders(court, case_type="134", case_number="1", year="2024")

        # List benches and case types (no CAPTCHA needed)
        benches = await client.list_benches(court)
        case_types = await client.list_case_types(court)

asyncio.run(main())
```

## Quick Start — District Courts

District courts use a 4-level hierarchy: State → District → Court Complex → Establishment. Discover courts dynamically, then search.

```python
from bharat_courts import DistrictCourtClient
from bharat_courts.captcha.ocr import OCRCaptchaSolver
from bharat_courts.districtcourts.parser import parse_complex_value

async def main():
    solver = OCRCaptchaSolver()

    async with DistrictCourtClient(captcha_solver=solver) as client:
        # 1. Discover the court hierarchy
        states = await client.list_states()          # {"8": "Bihar", "7": "Delhi", ...}
        districts = await client.list_districts("8")  # {"1": "Patna", "35": "Gaya", ...}
        complexes = await client.list_complexes("8", "1")  # {"1080010@2,3,4@Y": "Civil Court, Patna Sadar", ...}

        # 2. Parse the complex value to get the code and check if establishment is needed
        complex_val = list(complexes.keys())[0]
        complex_code, est_codes, needs_est = parse_complex_value(complex_val)
        est_code = est_codes[0] if needs_est else ""

        # 3. List case types (no CAPTCHA)
        case_types = await client.list_case_types("8", "1", complex_code, est_code)

        # 4. Search by party name (CAPTCHA auto-retried)
        cases = await client.case_status_by_party(
            state_code="8", dist_code="1",
            court_complex_code=complex_code, est_code=est_code,
            party_name="kumar", year="2024",
        )
        for case in cases:
            print(f"{case.case_number}: {case.petitioner} vs {case.respondent}")

        # 5. Search by case number
        cases = await client.case_status(
            state_code="8", dist_code="1",
            court_complex_code=complex_code, est_code=est_code,
            case_type="1", case_number="100", year="2024",
        )

        # 6. Get court orders
        orders = await client.court_orders(
            state_code="8", dist_code="1",
            court_complex_code=complex_code, est_code=est_code,
            case_type="1", case_number="100", year="2024",
        )

        # 7. Get cause list
        entries = await client.cause_list(
            state_code="8", dist_code="1",
            court_complex_code=complex_code, est_code=est_code,
            civil=True,
        )

asyncio.run(main())
```

## Available High Courts

Use `get_court(code)` with any of these codes:

| Code | Court | State Code |
|------|-------|------------|
| `delhi` | Delhi High Court | 26 |
| `bombay` | Bombay High Court | 1 |
| `calcutta` | Calcutta High Court | 16 |
| `madras` | Madras High Court | 10 |
| `allahabad` | Allahabad High Court | 13 |
| `karnataka` | Karnataka High Court | 3 |
| `kerala` | Kerala High Court | 4 |
| `gujarat` | Gujarat High Court | 17 |
| `punjab` | Punjab & Haryana High Court | 22 |
| `rajasthan` | Rajasthan High Court | 9 |
| `telangana` | Telangana High Court | 29 |
| `andhra` | Andhra Pradesh High Court | 2 |
| `patna` | Patna High Court | 8 |
| `gauhati` | Gauhati High Court | 6 |
| `orissa` | Orissa High Court | 11 |
| `mp` | Madhya Pradesh High Court | 23 |
| `jharkhand` | Jharkhand High Court | 7 |
| `chhattisgarh` | Chhattisgarh High Court | 18 |
| `himachal` | Himachal Pradesh High Court | 5 |
| `uttarakhand` | Uttarakhand High Court | 15 |
| `jammu` | J&K High Court | 12 |
| `manipur` | Manipur High Court | 25 |
| `meghalaya` | Meghalaya High Court | 21 |
| `sikkim` | Sikkim High Court | 24 |
| `tripura` | Tripura High Court | 20 |
| `sci` | Supreme Court of India | 0 |

## HCServicesClient Methods

| Method | CAPTCHA | Returns | Description |
|--------|---------|---------|-------------|
| `list_benches(court)` | No | `dict[str, str]` | Available benches |
| `list_case_types(court)` | No | `dict[str, str]` | Case type codes |
| `case_status(court, case_type, case_number, year)` | Yes | `list[CaseInfo]` | Search by case number |
| `case_status_by_party(court, party_name, year)` | Yes | `list[CaseInfo]` | Search by party name |
| `court_orders(court, case_type, case_number, year)` | Yes | `list[CaseOrder]` | Get orders for a case |
| `cause_list(court, civil=True)` | Yes | `list[CauseListPDF]` | Today's cause list PDFs |
| `download_order_pdf(pdf_url)` | No | `bytes` | Download order PDF |

## DistrictCourtClient Methods

All search methods require `state_code`, `dist_code`, `court_complex_code`, and `est_code` (use the discovery methods to find these).

| Method | CAPTCHA | Returns | Description |
|--------|---------|---------|-------------|
| `list_states()` | No | `dict[str, str]` | All 36 states/UTs with codes |
| `list_districts(state_code)` | No | `dict[str, str]` | Districts for a state |
| `list_complexes(state_code, dist_code)` | No | `dict[str, str]` | Court complexes (value format: `code@ests@flag`) |
| `list_establishments(state_code, dist_code, complex_code)` | No | `dict[str, str]` | Establishments (when flag=Y) |
| `list_case_types(state_code, dist_code, complex_code, est_code)` | No | `dict[str, str]` | Case type codes |
| `case_status(*, state_code, dist_code, court_complex_code, est_code, case_type, case_number, year)` | Yes | `list[CaseInfo]` | Search by case number |
| `case_status_by_party(*, state_code, dist_code, court_complex_code, est_code, party_name, year)` | Yes | `list[CaseInfo]` | Search by party name |
| `court_orders(*, state_code, dist_code, court_complex_code, est_code, case_type, case_number, year)` | Yes | `list[CaseOrder]` | Get orders for a case |
| `cause_list(*, state_code, dist_code, court_complex_code, est_code, civil=True)` | Yes | `list[CauseListEntry]` | Cause list entries |

Use `parse_complex_value(value)` from `bharat_courts.districtcourts.parser` to extract `(complex_code, est_codes, needs_establishment)` from the complex dropdown values.

## Data Models

All models support `to_dict()` and `to_json()` for serialization.

- **CaseInfo**: `case_number`, `case_type`, `cnr_number`, `petitioner`, `respondent`, `status`, `registration_date`, `court_name`
- **CaseOrder**: `order_date`, `order_type`, `judge`, `pdf_url`
- **CauseListPDF**: `serial_number`, `bench`, `cause_list_type`, `pdf_url`
- **CauseListEntry**: `serial_number`, `case_number`, `petitioner`, `respondent`, `court_number`, `judge`
- **JudgmentResult**: `title`, `case_number`, `court_name`, `judgment_date`, `judges`, `pdf_url`

## CAPTCHA Handling

Both HC Services and District Courts use Securimage CAPTCHAs. The OCR solver (`ddddocr`) has ~60% accuracy with automatic retry (up to 3 attempts with fresh sessions).

```python
from bharat_courts.captcha.ocr import OCRCaptchaSolver
solver = OCRCaptchaSolver()

# Or implement a custom solver:
from bharat_courts.captcha.base import CaptchaSolver
class MySolver(CaptchaSolver):
    async def solve(self, image_bytes: bytes) -> str:
        return "solved_text"
```

## Judgment Search Portal

```python
from bharat_courts import JudgmentSearchClient, get_court

async with JudgmentSearchClient() as client:
    result = await client.search(
        get_court("delhi"),
        from_date="01-01-2024",
        to_date="31-01-2024",
    )
    for j in result.items:
        print(f"{j.title} — {j.judgment_date}")
```

## Important Notes

- All methods are async — use `asyncio.run()` or `await`
- CAPTCHA is pinned to PHP session — the library handles session management automatically
- `rgyear` / `year` is mandatory for party name search
- Case type codes can be discovered via `list_case_types()`
- Rate limiting is built in (default 1 second between requests)
- District courts require dynamic court discovery (state → district → complex → establishment) unlike High Courts which use static `get_court()` codes
