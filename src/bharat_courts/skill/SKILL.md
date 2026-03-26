---
name: bharat-courts
description: Access Indian court data — search cases, download orders, and get cause lists from eCourts High Courts, District Courts, and the Supreme Court. Use when the user needs to look up Indian court cases, search by party name, get court orders or judgments, or access daily cause lists.
---

# Indian Court Data with bharat-courts

Async Python SDK for accessing Indian court data from eCourts portals.

## Installation

```bash
pip install bharat-courts[ocr]   # RECOMMENDED — ddddocr CAPTCHA solving, no auth needed
pip install bharat-courts[onnx]  # ONNX model — requires HF_TOKEN env var for HuggingFace auth
pip install bharat-courts[all]   # everything
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
        # Search by party name (year is mandatory)
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

## Judgment Search Portal

Search High Court judgments by keyword on judgments.ecourts.gov.in.

```python
from bharat_courts import JudgmentSearchClient
from bharat_courts.captcha.ocr import OCRCaptchaSolver

async def main():
    solver = OCRCaptchaSolver()

    async with JudgmentSearchClient(captcha_solver=solver) as client:
        # Single page search
        result = await client.search("right to privacy", search_opt="ALL", court_type="2")
        for j in result.items:
            print(f"{j.title} — {j.judgment_date}")

        # Paginate through all results
        async for page in client.search_all("right to privacy", search_opt="ALL"):
            for j in page.items:
                print(j.title)

        # Download PDFs
        result = await client.search("constitution")
        result.items = [await client.download_pdf(j) for j in result.items]

        # Batch download with automatic session reset every 25 downloads
        judgments = await client.download_pdfs(result.items, batch_size=25)

asyncio.run(main())
```

## Calcutta High Court (Direct)

Search orders/judgments directly on calcuttahighcourt.gov.in — has better PDF coverage than eCourts for Calcutta HC cases from September 2020 onwards.

```python
from bharat_courts import CalcuttaHCClient

async def main():
    async with CalcuttaHCClient() as client:
        # Search by case number
        orders = await client.search_orders(
            case_type="12",        # WPA
            case_number="12886",
            year="2024",
            establishment="appellate",  # or "original", "jalpaiguri", "portblair"
        )
        for order in orders:
            print(f"{order.order_date} | {order.judge} | {order.neutral_citation}")
            if order.pdf_url:
                pdf = await client.download_order_pdf(order.pdf_url)

asyncio.run(main())
```

### CalcuttaHCClient Methods

| Method | CAPTCHA | Returns | Description |
|--------|---------|---------|-------------|
| `search_orders(*, case_type, case_number, year, establishment="appellate", max_captcha_attempts=3)` | Yes | `list[CaseOrder]` | Search orders by case number |
| `download_order_pdf(pdf_url)` | No | `bytes` | Download order PDF |

`establishment` values: `"appellate"`, `"original"`, `"jalpaiguri"`, `"portblair"`.

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
| `list_case_types(court, *, bench_code="1")` | No | `dict[str, str]` | Case type codes for a bench |
| `case_status(court, *, case_type, case_number, year, bench_code="1")` | Yes | `list[CaseInfo]` | Search by case number |
| `case_status_by_party(court, *, party_name, year, bench_code="1", status_filter="Both")` | Yes | `list[CaseInfo]` | Search by party name |
| `court_orders(court, *, case_type, case_number, year, bench_code="1")` | Yes | `list[CaseOrder]` | Get orders for a case |
| `cause_list(court, *, civil=True, bench_code="1", causelist_date="")` | Yes | `list[CauseListPDF]` | Cause list PDFs (date format: DD-MM-YYYY) |
| `download_order_pdf(pdf_url)` | No | `bytes` | Download order PDF |

## JudgmentSearchClient Methods

| Method | CAPTCHA | Returns | Description |
|--------|---------|---------|-------------|
| `search(search_text, *, page=1, search_opt="PHRASE", court_type="2", max_captcha_attempts=3)` | Yes | `SearchResult` | Search judgments by keyword |
| `search_all(search_text, *, search_opt="PHRASE", court_type="2", max_captcha_attempts=3)` | Yes | `AsyncIterator[SearchResult]` | Paginate all results (auto re-auth on session expiry) |
| `download_pdf(judgment)` | No | `JudgmentResult` | Download PDF for a single judgment (sets `pdf_bytes` in place) |
| `download_pdfs(judgments, *, batch_size=25)` | No | `list[JudgmentResult]` | Batch download with auto session reset |

`search_opt` values: `"PHRASE"` (exact phrase), `"ANY"` (any word), `"ALL"` (all words).
`court_type` values: `"2"` (High Courts), `"3"` (Supreme Court Reports).

## DistrictCourtClient Methods

All search methods require `state_code`, `dist_code`, `court_complex_code`, and `est_code` (use the discovery methods to find these).

| Method | CAPTCHA | Returns | Description |
|--------|---------|---------|-------------|
| `list_states()` | No | `dict[str, str]` | All 36 states/UTs with codes |
| `list_districts(state_code)` | No | `dict[str, str]` | Districts for a state |
| `list_complexes(state_code, dist_code)` | No | `dict[str, str]` | Court complexes (value format: `code@ests@flag`) |
| `list_establishments(state_code, dist_code, complex_code)` | No | `dict[str, str]` | Establishments (when flag=Y) |
| `list_case_types(state_code, dist_code, complex_code, est_code="")` | No | `dict[str, str]` | Case type codes |
| `case_status(*, state_code, dist_code, court_complex_code, est_code="", case_type, case_number, year)` | Yes | `list[CaseInfo]` | Search by case number |
| `case_status_by_party(*, state_code, dist_code, court_complex_code, est_code="", party_name, year, status_filter="Both")` | Yes | `list[CaseInfo]` | Search by party name |
| `court_orders(*, state_code, dist_code, court_complex_code, est_code="", case_type, case_number, year)` | Yes | `list[CaseOrder]` | Get orders for a case |
| `cause_list(*, state_code, dist_code, court_complex_code, est_code="", court_no="", causelist_date="", civil=True)` | Yes | `list[CauseListEntry]` | Cause list entries |

Use `parse_complex_value(value)` from `bharat_courts.districtcourts.parser` to extract `(complex_code, est_codes, needs_establishment)` from the complex dropdown values.

## Data Models

All models support `to_dict()` and `to_json()` for serialization.

- **CaseInfo**: `case_number`, `case_type`, `cnr_number`, `filing_number`, `registration_number`, `registration_date`, `petitioner`, `respondent`, `status`, `court_name`, `judges`, `next_hearing_date`
- **CaseOrder**: `order_date`, `order_type`, `judge`, `pdf_url`, `pdf_bytes`, `order_text`
- **CauseListPDF**: `serial_number`, `bench`, `cause_list_type`, `pdf_url` (HC Services — one PDF per bench)
- **CauseListEntry**: `serial_number`, `case_number`, `case_type`, `petitioner`, `respondent`, `advocate_petitioner`, `advocate_respondent`, `court_number`, `judge`, `listing_date`, `item_number` (District Courts — structured entries)
- **JudgmentResult**: `title`, `court_name`, `case_number`, `judgment_date`, `judges`, `pdf_url`, `pdf_bytes`, `citation`, `bench_type`, `source_url`, `source_id`, `metadata`
- **SearchResult**: `items`, `total_count`, `page`, `page_size`, `has_next`, `total_pages` (paginated container)

## CAPTCHA Handling

Both HC Services and District Courts use Securimage CAPTCHAs. Two auto-solvers are available:

```python
# Option 1: ddddocr (pip install bharat-courts[ocr])
from bharat_courts.captcha.ocr import OCRCaptchaSolver
solver = OCRCaptchaSolver()  # ~60% accuracy, auto-retry with fresh sessions

# Option 2: ONNX model (pip install bharat-courts[onnx])
# REQUIRES HF_TOKEN env var — the model is downloaded from HuggingFace
# Get a token at https://huggingface.co/settings/tokens
# export HF_TOKEN=hf_...
from bharat_courts.captcha.onnx import ONNXCaptchaSolver
solver = ONNXCaptchaSolver()  # lighter, uses onnxruntime, needs HF auth

# Option 3: Manual input
from bharat_courts.captcha.manual import ManualCaptchaSolver
solver = ManualCaptchaSolver()  # prompts on stdin

# Option 4: Custom solver
from bharat_courts.captcha.base import CaptchaSolver
class MySolver(CaptchaSolver):
    async def solve(self, image_bytes: bytes) -> str:
        return "solved_text"
```

## Important Notes

- All methods are async — use `asyncio.run()` or `await`
- **Default CAPTCHA solver is OCRCaptchaSolver (ddddocr)** — no explicit solver needed if `bharat-courts[ocr]` is installed. Clients auto-detect the best available solver.
- **ONNXCaptchaSolver requires `HF_TOKEN`** — the ONNX model is hosted on HuggingFace which requires authentication. Set `export HF_TOKEN=hf_...` before use. Prefer OCRCaptchaSolver unless you have a specific reason to use ONNX.
- CAPTCHA is pinned to PHP session — the library creates fresh sessions on each retry automatically
- `year` is mandatory for party name search (server returns ERROR_VAL if empty)
- Case type codes are numeric and vary by court — discover via `list_case_types()`
- Rate limiting is built in (default 1 second between requests)
- District courts require dynamic court discovery (state → district → complex → establishment) unlike High Courts which use static `get_court()` codes
- JudgmentSearchClient only supports keyword search — there is no search by party name, CNR, or case number on the judgments portal
- Some order PDFs may not be uploaded on eCourts even when the case exists — `court_orders()` will return the URL but the PDF download may return an error from the server
