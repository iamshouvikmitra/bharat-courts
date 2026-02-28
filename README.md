# bharat-courts

> Async Python SDK for Indian court data — search cases, download orders, and access cause lists from eCourts and the Supreme Court.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/bharat-courts.svg)](https://pypi.org/project/bharat-courts/)

---

## What is this?

Access to court records is fundamental to legal transparency and the rule of law. India's eCourts platform holds millions of case records across 25+ High Courts and the Supreme Court — but programmatic access is difficult.

**bharat-courts** makes it easy. It provides a clean async Python interface to:

- **Search cases** by number, party name, or advocate across any High Court
- **Download court orders** and judgment PDFs
- **Get daily cause lists** — see which cases are being heard today, by bench
- **Look up case types and bench info** for all 25 High Courts
- **Automate CAPTCHA handling** with built-in OCR

Built for legal researchers, civic tech projects, legal aid organizations, journalists, and anyone working to make Indian judicial data more accessible. All responses are returned as typed Python dataclasses with JSON serialization.

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

### Search cases by party name

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
            party_name="state",
            year="2024",
        )
        for case in cases[:5]:
            print(f"{case.cnr_number}: {case.petitioner} v {case.respondent}")
            print(f"  Status: {case.status}")

asyncio.run(main())
```

```
DLHC010XXXXXXXXX: PETITIONER NAME v RESPONDENT NAME & ORS.
  Status: Pending
DLHC010XXXXXXXXX: PETITIONER NAME v UNION OF INDIA
  Status: Disposed
...
```

### Search by case number

```python
cases = await client.case_status(
    delhi,
    case_type="134",     # W.P.(C) — use list_case_types() to discover codes
    case_number="1",
    year="2024",
)
```

### Get today's cause list

```python
pdfs = await client.cause_list(delhi, civil=True)
for pdf in pdfs:
    print(f"{pdf.bench}")
    print(f"  PDF: {pdf.pdf_url}")
```

```
BENCH 1 (Division Bench)
  PDF: https://hcservices.ecourts.gov.in/hcservices/cases_qry/cases/display_causelist_pdf.php?...
BENCH 2 (Single Bench)
  PDF: https://hcservices.ecourts.gov.in/hcservices/cases_qry/cases/display_causelist_pdf.php?...
```

### List benches and case types (no CAPTCHA needed)

```python
benches = await client.list_benches(delhi)
# {'1': 'Principal Bench at Delhi'}

case_types = await client.list_case_types(delhi)
# {'134': 'W.P.(C)(CIVIL WRITS)-134', '27': 'W.P.(CRL)...', ...}
```

### Court registry

```python
from bharat_courts import get_court, list_high_courts

# Look up any court
delhi = get_court("delhi")       # Delhi High Court (state_code="26")
bombay = get_court("bombay")     # Bombay High Court (state_code="1")
sci = get_court("sci")           # Supreme Court of India

# List all High Courts
for court in list_high_courts():
    print(f"{court.code}: {court.name} (state_code={court.state_code})")
```

### JSON serialization

All models support `to_dict()` and `to_json()`:

```python
case = cases[0]
print(case.to_json(indent=2))
```

```json
{
  "case_number": "3/2024",
  "case_type": "3",
  "cnr_number": "DLHC010XXXXXXXXX",
  "petitioner": "PETITIONER NAME",
  "respondent": "RESPONDENT NAME & ORS.",
  "status": "Pending",
  "court_name": "Delhi High Court"
}
```

## Supported Portals

| Portal | Client | Status |
|--------|--------|--------|
| [HC Services](https://hcservices.ecourts.gov.in) | `HCServicesClient` | Fully working |
| [Judgment Search](https://judgments.ecourts.gov.in) | `JudgmentSearchClient` | Basic search |
| [Supreme Court](https://main.sci.gov.in) | `SCIClient` | Basic search |

### HC Services — Full API

| Method | CAPTCHA | Description |
|--------|---------|-------------|
| `list_benches()` | No | Available benches for a High Court |
| `list_case_types()` | No | Case type codes (W.P.(C) = 134, etc.) |
| `case_status()` | Yes | Search by case number |
| `case_status_by_party()` | Yes | Search by party name + year |
| `court_orders()` | Yes | Get orders for a case |
| `cause_list()` | Yes | Today's cause list PDFs by bench |
| `download_order_pdf()` | No | Download order/judgment PDF |

## CAPTCHA Handling

HC Services uses Securimage CAPTCHAs that are pinned to the PHP session. The built-in OCR solver (`ddddocr`) has ~60% accuracy — failed attempts are automatically retried with fresh sessions (up to 3 attempts by default).

```python
from bharat_courts.captcha.ocr import OCRCaptchaSolver

# Automatic OCR (requires pip install bharat-courts[ocr])
solver = OCRCaptchaSolver()
```

For higher accuracy, implement a custom solver:

```python
from bharat_courts.captcha.base import CaptchaSolver

class MyCaptchaSolver(CaptchaSolver):
    async def solve(self, image_bytes: bytes) -> str:
        # Send to a CAPTCHA service, ML model, etc.
        return "solved_text"

async with HCServicesClient(captcha_solver=MyCaptchaSolver()) as client:
    ...
```

Or use the manual solver for interactive use:

```python
from bharat_courts.captcha.manual import ManualCaptchaSolver

# Opens the CAPTCHA image and prompts on stdin
solver = ManualCaptchaSolver()
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
