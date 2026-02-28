# CLAUDE.md

Instructions for AI agents working on this codebase.

## Project Overview

bharat-courts is an async Python SDK for accessing Indian court data from eCourts portals. It provides programmatic access to case status, court orders, cause lists, and judgment search across 25+ High Courts and the Supreme Court.

## Development Commands

```bash
# Install (requires Python 3.11+, use python3.12 if system python is older)
pip install -e ".[all]"

# Run unit tests (43 tests, no network needed)
pytest

# Run single test
pytest tests/test_hcservices_parser.py::test_parse_case_status_json

# Lint + format
ruff check .
ruff format --check .

# Auto-fix lint issues
ruff check --fix .
ruff format .

# Live integration tests (requires network + ddddocr)
python examples/live_test_all.py
```

## Architecture

### Source layout: `src/bharat_courts/`

- **`models.py`** — All data models. Dataclasses with `_Serializable` mixin providing `to_dict()` and `to_json()`. Key types: `Court`, `CaseInfo`, `CaseOrder`, `CauseListPDF`, `JudgmentResult`, `SearchResult`.
- **`courts.py`** — Static registry of all courts with eCourts state codes. `get_court("delhi")` returns a `Court` object. Codes verified against live portal.
- **`config.py`** — Pydantic Settings with `BHARAT_COURTS_` env prefix. Loaded once as module-level `config` singleton.
- **`http.py`** — `RateLimitedClient` wrapping httpx with retry, rate limiting, SSL bypass, and browser-like headers.
- **`captcha/`** — Pluggable CAPTCHA solving. `CaptchaSolver` ABC → `ManualCaptchaSolver` (stdin) and `OCRCaptchaSolver` (ddddocr).
- **`hcservices/`** — Primary client for hcservices.ecourts.gov.in (fully working).
- **`judgments/`** — Client for judgments.ecourts.gov.in (basic).
- **`sci/`** — Client for main.sci.gov.in (basic).
- **`cli.py`** — Click CLI entry point.

### HC Services portal protocol

1. `GET main.php` → establishes `HCSERVICES_SESSID` cookie
2. `GET securimage/securimage_show.php` → CAPTCHA image (pinned to session)
3. `POST cases_qry/index_qry.php?action_code=showRecords` → case search (JSON response)
4. `POST cases_qry/index_qry.php` with `action_code=showCauseList` in body → cause list (HTML response)

Key details:
- `action_code` goes in **URL query string** for showRecords, but in **POST body** for showCauseList
- `rgyear` is **mandatory** for party name search — server returns `ERROR_VAL` if empty
- CAPTCHA is pinned to PHP session — must create a fresh session for each retry
- `fillCaseType` needs `court_code` (bench code), NOT `court_complex_code`
- Responses have BOM prefix (`\ufeff`) that must be stripped

### Response formats

- **showRecords** → JSON: `{"con":["[{...}]"], "totRecords":"N", "Error":""}`
  - `con[0]` is a JSON-encoded string of case records
  - Fields: `cino`, `case_no`, `case_no2`, `case_type`, `case_year`, `pet_name`, `res_name`
- **showCauseList** → HTML table with columns: Sr No | Bench | Cause List Type | View Causelist (PDF link)
- **fillHCBench / fillCaseType** → `code~name#` delimited text

### Error responses

- `{"Error":"ERROR_VAL"}` → missing/invalid required param (NOT a captcha error)
- `{"con":"Invalid Captcha"}` → wrong CAPTCHA text
- `{"Error":""}` with valid `con` → success

## Key Patterns

- **Async everywhere** — httpx AsyncClient, pytest-asyncio (mode=auto)
- **Dataclasses for DTOs** — no ORM, no Pydantic models for data (only for Settings)
- **`src/` layout** — prevents accidental imports during development
- **Pluggable CAPTCHA** — ABC with manual and OCR implementations
- **Browser-like headers** — User-Agent, X-Requested-With, Accept, Referer are required for scraping
- **`_post_with_captcha_retry()`** — creates fresh HTTP session per retry attempt to get new CAPTCHAs
- **respx** for HTTP mocking in tests (hooks into httpx natively)

## State Codes (verified)

Delhi=26, Bombay=1, Allahabad=13, Calcutta=16, Gauhati=6, Telangana=29, AP=2, Karnataka=3, Kerala=4, HP=5, Jharkhand=7, Patna=8, Rajasthan=9, Madras=10, Orissa=11, J&K=12, Uttarakhand=15, Gujarat=17, Chhattisgarh=18, Tripura=20, Meghalaya=21, P&H=22, MP=23, Sikkim=24, Manipur=25

## Testing

- **Unit tests** (`tests/`) — 43 tests, all offline. Parser tests use HTML/JSON fixtures in `tests/fixtures/`.
- **Live tests** (`examples/live_test_all.py`) — 8 integration tests against real portals. Requires ddddocr. ~60% CAPTCHA accuracy with auto-retry.
- **Mocking** — `respx` for HTTP, custom `CaptchaSolver` subclass returning fixed strings.

## Ruff Config

Python 3.11 target, 100-char line length, rules: E, F, I, N, W. Config in `pyproject.toml`.
