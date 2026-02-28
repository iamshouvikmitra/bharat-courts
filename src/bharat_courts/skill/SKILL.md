---
name: bharat-courts
description: Access Indian court data — search cases, download orders, and get cause lists from eCourts High Courts and the Supreme Court. Use when the user needs to look up Indian court cases, search by party name, get court orders or judgments, or access daily cause lists.
---

# Indian Court Data with bharat-courts

Async Python SDK for accessing Indian court data from eCourts portals.

## Installation

```bash
pip install bharat-courts[ocr]   # with automatic CAPTCHA solving
```

## Quick Start

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

## Available Courts

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

## Data Models

All models support `to_dict()` and `to_json()` for serialization.

- **CaseInfo**: `case_number`, `case_type`, `cnr_number`, `petitioner`, `respondent`, `status`, `registration_date`, `court_name`
- **CaseOrder**: `order_date`, `order_type`, `judge`, `pdf_url`
- **CauseListPDF**: `serial_number`, `bench`, `cause_list_type`, `pdf_url`
- **JudgmentResult**: `title`, `case_number`, `court_name`, `judgment_date`, `judges`, `pdf_url`

## CAPTCHA Handling

HC Services uses Securimage CAPTCHAs. The OCR solver (`ddddocr`) has ~60% accuracy with automatic retry (up to 3 attempts with fresh sessions).

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
- `rgyear` is mandatory for party name search
- Case type codes (e.g. "134" for W.P.(C)) can be discovered via `list_case_types()`
- Rate limiting is built in (default 1 second between requests)
