# bharat-courts

> Async Python SDK for Indian court data — search cases, download orders, and access cause lists from eCourts and the Supreme Court.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/bharat-courts.svg)](https://pypi.org/project/bharat-courts/)

---

## What is this?

India's eCourts platform holds millions of case records across 25+ High Courts and the Supreme Court — but there's no official API. Checking case status means navigating clunky portals, solving CAPTCHAs by hand, and copy-pasting results one at a time.

**bharat-courts** fixes that. It gives you — and your AI assistant — direct programmatic access to:

- **Track matters** — search by case number, party name, or advocate across any High Court
- **Download orders & judgments** — get PDFs for all orders in a case with one call
- **Monitor cause lists** — see which cases are listed before which bench, every day
- **Search Supreme Court judgments** — by party name, year, or keyword
- **Automate CAPTCHA handling** — built-in OCR solver, or plug in your own

Works standalone as a Python library, as a CLI tool, or as an **AI agent skill** — install it into Claude Code, GitHub Copilot, or any MCP-compatible assistant and ask questions in plain English.

Built for practicing lawyers, litigation teams, legal researchers, legal aid organizations, and legal tech builders.

## Installation

```bash
pip install bharat-courts

# With automatic CAPTCHA solving (recommended)
pip install bharat-courts[ocr]

# With CLI
pip install bharat-courts[cli]

# Everything (OCR + CLI + dev tools)
pip install bharat-courts[all]
```

**Requires Python 3.11+**

## Quick Start

### Find all pending matters for your client

```python
import asyncio
from bharat_courts import get_court, HCServicesClient
from bharat_courts.captcha.ocr import OCRCaptchaSolver

async def main():
    delhi = get_court("delhi")
    solver = OCRCaptchaSolver()

    async with HCServicesClient(captcha_solver=solver) as client:
        cases = await client.case_status_by_party(
            delhi,
            party_name="Reliance Industries",
            year="2024",
            status_filter="Pending",
        )
        for case in cases:
            print(f"{case.case_number}: {case.petitioner} v {case.respondent}")
            print(f"  Next hearing: {case.next_hearing_date}")

asyncio.run(main())
```

### Check case status and download orders

```python
async with HCServicesClient(captcha_solver=solver) as client:
    # Look up a specific writ petition
    cases = await client.case_status(
        get_court("bombay"),
        case_type="134",       # W.P.(C) — use list_case_types() to discover codes
        case_number="4520",
        year="2023",
    )
    print(f"Status: {cases[0].status}")
    print(f"Judges: {', '.join(cases[0].judges)}")

    # Download all orders for the case
    orders = await client.court_orders(
        get_court("bombay"),
        case_type="134",
        case_number="4520",
        year="2023",
    )
    for order in orders:
        print(f"{order.order_date} — {order.order_type} by {order.judge}")
        pdf = await client.download_order_pdf(order.pdf_url)
        with open(f"order_{order.order_date}.pdf", "wb") as f:
            f.write(pdf)
```

### Get tomorrow's cause list before court

```python
pdfs = await client.cause_list(
    get_court("delhi"),
    civil=True,
    causelist_date="03-03-2026",   # DD-MM-YYYY
)
for pdf in pdfs:
    print(f"{pdf.bench} — {pdf.cause_list_type}")
    print(f"  Download: {pdf.pdf_url}")
```

### Search Supreme Court judgments

```python
from bharat_courts import SCIClient

async with SCIClient() as client:
    judgments = await client.search_by_party("union of india")
    for j in judgments:
        print(f"{j.judgment_date}: {j.title}")
        print(f"  Bench: {', '.join(j.judges)}")
```

### Use with AI agents (Claude Code, Copilot, etc.)

Install the bundled skill so your AI assistant can look up court data for you in natural language:

```bash
bharat-courts install-skills
```

Then just ask your AI agent:

> "Find all pending writ petitions for Tata Motors in Delhi High Court from 2024"

> "Download the latest order in WP(C) 4520/2023 before the Bombay High Court"

> "What's on the cause list for Karnataka High Court tomorrow?"

> "Search Supreme Court judgments on right to privacy from last year"

The agent uses bharat-courts under the hood — handles CAPTCHA, sessions, and parsing automatically.

### JSON serialization

All models support `to_dict()` and `to_json()` — pipe results into spreadsheets, dashboards, or case management tools:

```python
import json

cases = await client.case_status_by_party(delhi, party_name="HDFC", year="2024")
# Export to JSON for your case tracker
with open("matters.json", "w") as f:
    json.dump([c.to_dict(exclude_none=True) for c in cases], f, indent=2)
```

```json
[
  {
    "case_number": "W.P.(C) 3/2024",
    "cnr_number": "DLHC010582482024",
    "petitioner": "HDFC BANK LTD.",
    "respondent": "UNION OF INDIA & ORS.",
    "status": "Pending",
    "next_hearing_date": "2026-04-15",
    "judges": ["HON'BLE MR. JUSTICE ..."]
  }
]
```

## Supported Portals

| Portal | Client | Status |
|--------|--------|--------|
| [HC Services](https://hcservices.ecourts.gov.in) | `HCServicesClient` | Fully working |
| [Judgment Search](https://judgments.ecourts.gov.in) | `JudgmentSearchClient` | Basic search |
| [Supreme Court](https://main.sci.gov.in) | `SCIClient` | Basic search |

## API Reference

### `HCServicesClient`

Primary client for High Court case data via `hcservices.ecourts.gov.in`.

```python
from bharat_courts import HCServicesClient

client = HCServicesClient(
    config=None,            # BharatCourtsConfig | None — uses global config singleton if None
    captcha_solver=None,    # CaptchaSolver | None — defaults to ManualCaptchaSolver()
    http_client=None,       # RateLimitedClient | None — creates one internally if None
)
```

Use as an async context manager:

```python
async with HCServicesClient(captcha_solver=solver) as client:
    ...
```

---

#### `list_benches(court) -> dict[str, str]`

Get available benches for a High Court. **No CAPTCHA required.**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `court` | `Court` | Yes | Court object from `get_court()` |

**Returns:** `dict[str, str]` — mapping of bench code to bench name.

```python
delhi = get_court("delhi")
benches = await client.list_benches(delhi)
# {'1': 'Principal Bench at Delhi'}

bombay = get_court("bombay")
benches = await client.list_benches(bombay)
# {'1': 'Principal Seat at Bombay', '2': 'Nagpur Bench', '3': 'Aurangabad Bench', '4': 'Goa Bench'}
```

---

#### `list_case_types(court, *, bench_code="1") -> dict[str, str]`

Get available case type codes for a court bench. **No CAPTCHA required.**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `court` | `Court` | Yes | — | Court object |
| `bench_code` | `str` | No | `"1"` | Bench code from `list_benches()` |

**Returns:** `dict[str, str]` — mapping of case type code to name.

```python
case_types = await client.list_case_types(delhi)
# {'134': 'W.P.(C)(CIVIL WRITS)-134', '27': 'W.P.(CRL)-27', '3': 'EL.PET.-3', ...}
```

---

#### `case_status(court, *, case_type, case_number, year, bench_code="1") -> list[CaseInfo]`

Look up case status by case number. **CAPTCHA required** (auto-retried).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `court` | `Court` | Yes | — | Court object |
| `case_type` | `str` | Yes | — | Numeric case type code (use `list_case_types()` to discover) |
| `case_number` | `str` | Yes | — | Case number without type/year |
| `year` | `str` | Yes | — | Registration year, e.g. `"2024"` |
| `bench_code` | `str` | No | `"1"` | Bench code from `list_benches()` |

**Returns:** `list[CaseInfo]` — matching cases.

```python
cases = await client.case_status(
    delhi,
    case_type="134",      # W.P.(C)
    case_number="1",
    year="2024",
)
for case in cases:
    print(f"{case.cnr_number}: {case.petitioner} v {case.respondent}")
    print(f"  Status: {case.status}, Next hearing: {case.next_hearing_date}")
```

---

#### `case_status_by_party(court, *, party_name, year, bench_code="1", status_filter="Both") -> list[CaseInfo]`

Search cases by party name. **CAPTCHA required** (auto-retried).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `court` | `Court` | Yes | — | Court object |
| `party_name` | `str` | Yes | — | Petitioner or respondent name (min 3 characters) |
| `year` | `str` | Yes | — | Registration year — **mandatory**, server returns error if empty |
| `bench_code` | `str` | No | `"1"` | Bench code |
| `status_filter` | `str` | No | `"Both"` | `"Pending"`, `"Disposed"`, or `"Both"` |

**Returns:** `list[CaseInfo]` — matching cases.

```python
cases = await client.case_status_by_party(
    delhi,
    party_name="state",
    year="2024",
    status_filter="Pending",
)
for case in cases:
    print(f"{case.case_number}: {case.petitioner} v {case.respondent}")
```

---

#### `court_orders(court, *, case_type, case_number, year, bench_code="1") -> list[CaseOrder]`

Get court orders for a case. **CAPTCHA required** (auto-retried).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `court` | `Court` | Yes | — | Court object |
| `case_type` | `str` | Yes | — | Numeric case type code |
| `case_number` | `str` | Yes | — | Case number |
| `year` | `str` | Yes | — | Registration year |
| `bench_code` | `str` | No | `"1"` | Bench code |

**Returns:** `list[CaseOrder]` — orders with dates, types, judges, and PDF URLs.

```python
orders = await client.court_orders(
    delhi,
    case_type="134",
    case_number="1",
    year="2024",
)
for order in orders:
    print(f"{order.order_date}: {order.order_type} by {order.judge}")
    if order.pdf_url:
        pdf_bytes = await client.download_order_pdf(order.pdf_url)
        with open(f"order_{order.order_date}.pdf", "wb") as f:
            f.write(pdf_bytes)
```

---

#### `cause_list(court, *, civil=True, bench_code="1", causelist_date="") -> list[CauseListPDF]`

Get cause list PDFs for a court. **CAPTCHA required** (auto-retried).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `court` | `Court` | Yes | — | Court object |
| `civil` | `bool` | No | `True` | `True` for civil, `False` for criminal |
| `bench_code` | `str` | No | `"1"` | Bench code |
| `causelist_date` | `str` | No | `""` (today) | Date in `DD-MM-YYYY` format |

**Returns:** `list[CauseListPDF]` — one entry per bench with bench name, list type, and PDF URL.

```python
pdfs = await client.cause_list(delhi, civil=True)
for pdf in pdfs:
    print(f"#{pdf.serial_number} {pdf.bench} — {pdf.cause_list_type}")
    print(f"  PDF: {pdf.pdf_url}")

# Criminal cause list for a specific date
criminal_pdfs = await client.cause_list(
    delhi,
    civil=False,
    causelist_date="15-01-2025",
)
```

---

#### `download_order_pdf(pdf_url) -> bytes`

Download an order or judgment PDF. **No CAPTCHA required.**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pdf_url` | `str` | Yes | URL from `CaseOrder.pdf_url` or `CauseListPDF.pdf_url` |

**Returns:** `bytes` — raw PDF file content.

```python
pdf_bytes = await client.download_order_pdf(order.pdf_url)
with open("order.pdf", "wb") as f:
    f.write(pdf_bytes)
```

---

### `JudgmentSearchClient`

Client for the eCourts judgment search portal (`judgments.ecourts.gov.in`).

```python
from bharat_courts import JudgmentSearchClient

async with JudgmentSearchClient(captcha_solver=solver) as client:
    ...
```

---

#### `search(search_text, *, search_opt="PHRASE", court_type="2", max_captcha_attempts=3) -> SearchResult`

Search for judgments by keyword. **CAPTCHA required.**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `search_text` | `str` | Yes | — | Search query text |
| `search_opt` | `str` | No | `"PHRASE"` | `"PHRASE"`, `"ANY"`, or `"ALL"` |
| `court_type` | `str` | No | `"2"` | `"2"` for High Courts, `"3"` for SCR |
| `max_captcha_attempts` | `int` | No | `3` | Max CAPTCHA retry attempts |

**Returns:** `SearchResult` — contains `items: list[JudgmentResult]`, `total_count`, pagination info.

```python
from bharat_courts import JudgmentSearchClient
from bharat_courts.captcha.ocr import OCRCaptchaSolver

async with JudgmentSearchClient(captcha_solver=OCRCaptchaSolver()) as client:
    results = await client.search("right to privacy")
    print(f"Found {results.total_count} results")
    for judgment in results.items:
        print(f"{judgment.title}")
        print(f"  Court: {judgment.court_name}, Date: {judgment.judgment_date}")
        print(f"  Bench: {judgment.bench_type}, Judges: {', '.join(judgment.judges)}")
```

---

#### `download_pdf(judgment) -> JudgmentResult`

Download the PDF for a judgment result.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `judgment` | `JudgmentResult` | Yes | A result from `search()` |

**Returns:** `JudgmentResult` — the same object with `pdf_bytes` populated.

```python
judgment = results.items[0]
judgment = await client.download_pdf(judgment)
with open("judgment.pdf", "wb") as f:
    f.write(judgment.pdf_bytes)
```

---

### `SCIClient`

Client for the Supreme Court of India (`main.sci.gov.in`). **No CAPTCHA required.**

```python
from bharat_courts import SCIClient

# Note: no captcha_solver parameter — SCI doesn't use CAPTCHAs
async with SCIClient() as client:
    ...
```

---

#### `search_by_year(year, month=None) -> list[JudgmentResult]`

Search Supreme Court judgments by year and optional month.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `year` | `int` | Yes | — | Year to search, e.g. `2024` |
| `month` | `int \| None` | No | `None` | Month (1-12). If `None`, searches the full year. |

**Returns:** `list[JudgmentResult]`

```python
from bharat_courts import SCIClient

async with SCIClient() as client:
    # All judgments from June 2024
    judgments = await client.search_by_year(2024, month=6)
    for j in judgments:
        print(f"{j.judgment_date}: {j.title}")

    # All judgments from 2024
    all_2024 = await client.search_by_year(2024)
```

---

#### `search_by_party(party_name) -> list[JudgmentResult]`

Search Supreme Court judgments by party name.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `party_name` | `str` | Yes | Party name to search |

**Returns:** `list[JudgmentResult]`

```python
judgments = await client.search_by_party("union of india")
for j in judgments:
    print(f"{j.case_number}: {j.title}")
```

---

#### `download_pdf(judgment) -> JudgmentResult`

Download the PDF for a Supreme Court judgment.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `judgment` | `JudgmentResult` | Yes | A result from search methods |

**Returns:** `JudgmentResult` — same object with `pdf_bytes` populated.

---

### Court Registry Functions

```python
from bharat_courts import get_court, get_court_by_name, list_high_courts, list_all_courts
```

#### `get_court(code) -> Court | None`

Look up a court by its code. Case-insensitive.

```python
get_court("delhi")          # Delhi High Court
get_court("bombay-nagpur")  # Bombay HC, Nagpur Bench
get_court("sci")            # Supreme Court of India
get_court("nonexistent")    # None
```

#### `get_court_by_name(name) -> Court | None`

Look up a court by its full name. Case-insensitive exact match.

```python
get_court_by_name("Delhi High Court")  # Court(name="Delhi High Court", ...)
```

#### `list_high_courts() -> list[Court]`

Returns all 29 High Court entries (25 HCs + bench-specific entries for Bombay and Allahabad).

#### `list_all_courts() -> list[Court]`

Returns all 30 courts (Supreme Court + all High Courts).

#### Module-level constants

```python
from bharat_courts import ALL_COURTS, SUPREME_COURT

SUPREME_COURT  # Court(name="Supreme Court of India", code="sci", state_code="0")
ALL_COURTS     # list of all 30 Court objects
```

---

### Data Models

All models are Python dataclasses with `to_dict()` and `to_json()` serialization methods.

```python
# Available on all models
model.to_dict(exclude_none=False)   # -> dict (dates become ISO strings, enums become values)
model.to_json(indent=None, exclude_none=False)  # -> JSON string
```

#### `Court`

```python
@dataclass(frozen=True)
class Court:
    name: str                   # "Delhi High Court"
    code: str                   # "delhi"
    state_code: str             # "26"
    court_type: CourtType       # CourtType.HIGH_COURT
    bench: str | None = None    # "Lucknow Bench" (for bench-specific entries)

    @property
    def slug(self) -> str       # code lowercased, spaces replaced with hyphens
```

#### `CourtType`

```python
class CourtType(str, Enum):
    SUPREME_COURT  = "supreme_court"
    HIGH_COURT     = "high_court"
    DISTRICT_COURT = "district_court"
    TRIBUNAL       = "tribunal"
```

#### `CaseInfo`

Returned by `case_status()` and `case_status_by_party()`.

```python
@dataclass
class CaseInfo:
    case_number: str                        # "3/2024"
    case_type: str                          # Numeric code, e.g. "3"
    cnr_number: str = ""                    # "DLHC010582482024"
    filing_number: str = ""
    registration_number: str = ""
    registration_date: date | None = None
    petitioner: str = ""
    respondent: str = ""
    status: str = ""                        # "Pending" | "Disposed"
    court_name: str = ""
    judges: list[str] = []
    next_hearing_date: date | None = None
```

#### `CaseOrder`

Returned by `court_orders()`.

```python
@dataclass
class CaseOrder:
    order_date: date
    order_type: str             # "Judgment" | "Order" | "Interim Order"
    judge: str = ""
    pdf_url: str = ""
    pdf_bytes: bytes | None = None   # populated by download_order_pdf(); excluded from serialization
    order_text: str = ""
```

#### `CauseListPDF`

Returned by `cause_list()`.

```python
@dataclass
class CauseListPDF:
    serial_number: int
    bench: str                  # "Division Bench"
    cause_list_type: str = ""   # "COMPLETE CAUSE LIST"
    pdf_url: str = ""
    pdf_bytes: bytes | None = None   # excluded from serialization
```

#### `JudgmentResult`

Returned by `JudgmentSearchClient.search()`, `SCIClient.search_by_year()`, and `SCIClient.search_by_party()`.

```python
@dataclass
class JudgmentResult:
    title: str
    court_name: str
    case_number: str = ""
    judgment_date: date | None = None
    judges: list[str] = []
    pdf_url: str = ""
    pdf_bytes: bytes | None = None   # populated by download_pdf(); excluded from serialization
    citation: str = ""
    bench_type: str = ""             # "Division Bench" | "Single Bench" | "Full Bench"
    source_url: str = ""
    source_id: str = ""
    metadata: dict = {}
```

#### `SearchResult`

Returned by `JudgmentSearchClient.search()`.

```python
@dataclass
class SearchResult:
    items: list[CaseInfo | JudgmentResult | CauseListEntry] = []
    total_count: int = 0
    page: int = 1
    page_size: int = 10
    has_next: bool = False

    @property
    def total_pages(self) -> int   # ceil(total_count / page_size)
```

#### `CauseListEntry`

Structured cause list data (for parsed cause list entries).

```python
@dataclass
class CauseListEntry:
    serial_number: int
    case_number: str
    case_type: str = ""
    petitioner: str = ""
    respondent: str = ""
    advocate_petitioner: str = ""
    advocate_respondent: str = ""
    court_number: str = ""
    judge: str = ""
    listing_date: date | None = None
    item_number: str = ""
```

---

### CAPTCHA Solvers

All solvers implement the `CaptchaSolver` abstract base class:

```python
from bharat_courts.captcha.base import CaptchaSolver

class CaptchaSolver(ABC):
    @abstractmethod
    async def solve(self, image_bytes: bytes) -> str:
        """Given raw CAPTCHA image bytes, return the solved text."""
```

#### `OCRCaptchaSolver`

Automatic CAPTCHA solving using `ddddocr`. Requires `pip install bharat-courts[ocr]`.

```python
from bharat_courts.captcha.ocr import OCRCaptchaSolver

solver = OCRCaptchaSolver(
    preprocess=False,    # Apply image binarization + median filter before OCR
    threshold=128,       # Binarization threshold (0-255), used if preprocess=True
)
```

~60% accuracy. Failed attempts are automatically retried with fresh sessions.

#### `ManualCaptchaSolver`

Interactive solver that saves the CAPTCHA image and prompts the user.

```python
from bharat_courts.captcha.manual import ManualCaptchaSolver

# Prompt on stdin (saves image to /tmp/*.png for viewing)
solver = ManualCaptchaSolver()

# Or provide a custom callback (sync or async)
solver = ManualCaptchaSolver(callback=my_captcha_handler)
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `callback` | `Callable[[bytes], str \| Awaitable[str]] \| None` | No | `None` | Custom handler. Receives image bytes, returns solved text. If `None`, prompts on stdin. |

#### Custom Solver

Implement `CaptchaSolver` for your own solving strategy:

```python
from bharat_courts.captcha.base import CaptchaSolver

class MyCaptchaSolver(CaptchaSolver):
    async def solve(self, image_bytes: bytes) -> str:
        # Send to a CAPTCHA solving service, ML model, etc.
        return "solved_text"

async with HCServicesClient(captcha_solver=MyCaptchaSolver()) as client:
    ...
```

## CLI

```bash
# List all courts
bharat-courts courts
bharat-courts courts --type hc   # High Courts only

# Search case status (requires CAPTCHA — uses ManualCaptchaSolver by default)
bharat-courts search delhi --case-type 134 --case-number 1 --year 2024

# Get cause list
bharat-courts cause-list delhi
bharat-courts cause-list delhi --date 01-03-2026

# Get court orders
bharat-courts orders delhi --case-type 134 --case-number 1 --year 2024

# Search judgments
bharat-courts judgments delhi --from-date 01-01-2024 --to-date 31-01-2024

# Supreme Court
bharat-courts sci --year 2024 --month 6

# Install AI agent skills (Claude Code, Copilot, etc.)
bharat-courts install-skills
```

## Configuration

Environment variables with `BHARAT_COURTS_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `BHARAT_COURTS_REQUEST_DELAY` | `1.0` | Seconds between requests |
| `BHARAT_COURTS_TIMEOUT` | `30` | Request timeout (seconds) |
| `BHARAT_COURTS_MAX_RETRIES` | `3` | Retry count on failure |
| `BHARAT_COURTS_LOG_LEVEL` | `INFO` | Logging level |

Or use a `.env` file. See [.env.example](.env.example).

## Supported Courts

All 25 High Courts with verified eCourts state codes:

| Court | Code | State Code |
|-------|------|------------|
| Allahabad HC | `allahabad` | 13 |
| Andhra Pradesh HC | `andhra` | 2 |
| Bombay HC | `bombay` | 1 |
| Calcutta HC | `calcutta` | 16 |
| Chhattisgarh HC | `chhattisgarh` | 18 |
| Delhi HC | `delhi` | 26 |
| Gauhati HC | `gauhati` | 6 |
| Gujarat HC | `gujarat` | 17 |
| Himachal Pradesh HC | `himachal` | 5 |
| J&K HC | `jammu` | 12 |
| Jharkhand HC | `jharkhand` | 7 |
| Karnataka HC | `karnataka` | 3 |
| Kerala HC | `kerala` | 4 |
| Madhya Pradesh HC | `mp` | 23 |
| Madras HC | `madras` | 10 |
| Manipur HC | `manipur` | 25 |
| Meghalaya HC | `meghalaya` | 21 |
| Orissa HC | `orissa` | 11 |
| Patna HC | `patna` | 8 |
| Punjab & Haryana HC | `punjab` | 22 |
| Rajasthan HC | `rajasthan` | 9 |
| Sikkim HC | `sikkim` | 24 |
| Telangana HC | `telangana` | 29 |
| Tripura HC | `tripura` | 20 |
| Uttarakhand HC | `uttarakhand` | 15 |
| Supreme Court | `sci` | 0 |

Bombay and Allahabad HCs also have bench-specific entries (e.g., `bombay-nagpur`, `allahabad-lucknow`).

## Contributing

Contributions are welcome! Here's how to get set up.

### Prerequisites

- **Python 3.11+** — check with `python3 --version`
- **git**

### Dev environment setup

```bash
# 1. Fork and clone
git clone https://github.com/<your-username>/bharat-courts.git
cd bharat-courts

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Linux/macOS
# .venv\Scripts\activate    # Windows

# 3. Install with all extras (OCR, CLI, dev tools)
pip install -e ".[all]"

# 4. Verify everything works
pytest                                    # 43 unit tests, no network needed
ruff check . && ruff format --check .     # lint + format check
```

### Running tests

```bash
# Unit tests (fast, offline)
pytest

# Single test file
pytest tests/test_hcservices_parser.py

# Single test
pytest tests/test_hcservices_parser.py::test_parse_case_status_json

# With verbose output
pytest -v

# Live integration tests against real eCourts portals (requires ddddocr + network)
python examples/live_test_all.py
```

### Code style

The project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
# Check for issues
ruff check .

# Auto-fix what's possible
ruff check --fix .

# Format code
ruff format .
```

Config is in `pyproject.toml` — Python 3.11 target, 100-char line length, rules: E/F/I/N/W.

### Project structure

```
src/bharat_courts/
├── __init__.py          # Public API exports
├── models.py            # Dataclasses: CaseInfo, CaseOrder, CauseListPDF, etc.
├── config.py            # Pydantic Settings (BHARAT_COURTS_ env prefix)
├── http.py              # Rate-limited async HTTP client (httpx)
├── courts.py            # Registry of 25+ HCs with eCourts codes
├── captcha/
│   ├── base.py          # CaptchaSolver ABC
│   ├── manual.py        # Stdin/callback solver
│   └── ocr.py           # ddddocr-based solver
├── hcservices/          # HC Services portal (primary, fully working)
│   ├── client.py        # HCServicesClient
│   ├── endpoints.py     # URL + form builders
│   └── parser.py        # JSON + HTML response parsers
├── judgments/            # Judgment Search portal (basic)
│   ├── client.py
│   ├── endpoints.py
│   └── parser.py
├── sci/                 # Supreme Court (basic)
│   ├── client.py
│   └── parser.py
└── cli.py               # Click CLI entry point
```

### Areas where help is needed

- **Better CAPTCHA solving** — the ddddocr OCR is ~60% accurate; a fine-tuned model or alternative approach would help
- **District court support** — eCourts has district court portals with a different API
- **Judgment Search portal** — the `JudgmentSearchClient` needs more thorough testing and pagination support
- **Supreme Court client** — `SCIClient` is basic; the SCI website structure changes frequently
- **More High Court coverage** — test the client against courts beyond Delhi/Bombay/Allahabad
- **Documentation** — API docs, more examples, tutorials

### Submitting changes

1. Fork the repo and create a branch (`git checkout -b my-feature`)
2. Make your changes
3. Run `pytest` and `ruff check .` to ensure tests pass and code is clean
4. Commit with a descriptive message
5. Open a pull request

## How it works

The eCourts HC Services portal (`hcservices.ecourts.gov.in`) uses a PHP backend with:

1. **Session cookies** — `GET main.php` establishes `HCSERVICES_SESSID`
2. **Securimage CAPTCHAs** — pinned to the session (same image within one session)
3. **AJAX POST requests** — `cases_qry/index_qry.php` with `action_code` parameter
4. **JSON responses** — `{"con": ["[{...}]"], "totRecords": N, "Error": ""}`

This library handles all of this transparently — session management, CAPTCHA solving with retry, request/response parsing, and rate limiting.

## License

[MIT](LICENSE)
