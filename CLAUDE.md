# CLAUDE.md

Instructions for AI agents working on this codebase.

## Project Overview

bharat-courts is an async Python SDK for accessing Indian court data. Two complementary surfaces:

1. **Live clients** (`hcservices`, `districtcourts`, `calcuttahc`, `judgments`, `sci`) — scrape the official eCourts portals. CAPTCHA-gated, rate-limited, can answer "current case status / cause list / orders in progress". This is the original SDK.
2. **Archive client** (`archive`, opt-in via `[archive]` extra) — DuckDB queries against the public AWS Open Data buckets (SCI 1950→present + 25 HCs, CC-BY-4.0). No CAPTCHA, no rate limits, but lags by 2–3 months. Used for historical research and bulk PDF retrieval.

Coverage: 25+ High Courts, 700+ District Courts, the Supreme Court, plus the archive.

## Development Commands

```bash
# Install (requires Python 3.11+, use python3.12 if system python is older)
pip install -e ".[all]"

# Run unit tests (226 tests, no network needed)
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

- **`models.py`** — All data models. Dataclasses with `_Serializable` mixin providing `to_dict()` and `to_json()`. Key types: `Court`, `CaseInfo`, `CaseOrder`, `CauseListPDF`, `JudgmentResult`, `Judgment`, `SearchResult`. `Judgment` is the unified type used by the archive; `JudgmentResult` is the older type used by `JudgmentSearchClient`.
- **`courts.py`** — Static registry of all courts with eCourts state codes. `get_court("delhi")` returns a `Court` object. Also: `get_court_by_state_code("26")` (used by the archive to resolve HC partitions), `infer_court_from_cnr("DLHC...")` (4-letter prefix → Court, covers all 25 HCs + SCI). Codes verified against live portal.
- **`config.py`** — Pydantic Settings with `BHARAT_COURTS_` env prefix. Loaded once as module-level `config` singleton.
- **`http.py`** — `RateLimitedClient` wrapping httpx with retry, rate limiting, SSL bypass, and browser-like headers. Used by the live clients; the archive uses plain `httpx.AsyncClient` (no rate limiting needed for S3).
- **`captcha/`** — Pluggable CAPTCHA solving. `CaptchaSolver` ABC → `ManualCaptchaSolver` (stdin), `OCRCaptchaSolver` (ddddocr), `ONNXCaptchaSolver`. Only the live clients use these — the archive is CAPTCHA-free.
- **`hcservices/`** — Primary live client for hcservices.ecourts.gov.in (fully working).
- **`districtcourts/`** — Live client for services.ecourts.gov.in (700+ courts).
- **`calcuttahc/`** — Direct-website client for calcuttahighcourt.gov.in.
- **`judgments/`** — Live client for judgments.ecourts.gov.in.
- **`sci/`** — Live client for www.sci.gov.in (homepage feed only; case-no search not yet wired).
- **`archive/`** — Opt-in (`[archive]` extra). DuckDB over AWS Open Data parquet shards + per-tar / per-PDF caching. See "Archive module" below.
- **`cli.py`** — Click CLI entry point. Command groups mirror SDK module names.

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

### Archive module (`src/bharat_courts/archive/`)

Opt-in module that mirrors the public AWS Open Data judgment buckets locally.
Complementary to the live clients — use the archive for **historical** queries
(case decided 2+ months ago) and the live clients for **current** state (case
status, hearings, in-progress orders).

**Buckets** (both public, `ap-south-1`, CC-BY-4.0, maintained by Dattam Labs):
- `s3://indian-supreme-court-judgments/` (SCI, 1950→present, bi-monthly updates)
- `s3://indian-high-court-judgments/` (25 HCs, quarterly updates)

**Modules**:
- `client.py` — `ArchiveClient` async facade: `search`, `iter_judgments` (LIMIT/OFFSET streaming with stable sort), `fetch_pdf` (routes SCI vs HC), `count`, `cache_info`.
- `metadata.py` — `_ArchiveQuery` runs DuckDB SQL against the parquet glob (or local paths from the cache). Anonymous S3 via `CREATE SECRET (TYPE S3, KEY_ID '', SECRET '')`. Always disable the progress bar (`PRAGMA disable_progress_bar`) — it pollutes non-TTY output.
- `metadata_cache.py` — `_MetadataCache` mirrors parquet shards under `~/.cache/bharat-courts/archive/metadata/` with mtime TTL (default 30 days). HC needs per-year LIST to discover bench parquets; listings are JSON-cached. Used only when partition is fully resolved (year + court for HC; year for SCI).
- `storage.py` — `_PdfStorage` for the PDF cache. HC = direct GET per file (~250 KB). SCI = per-year tar (~40–500 MB) downloaded once, random-access via `tarfile`. LRU eviction with 5 GiB default cap (`BHARAT_COURTS_ARCHIVE_CACHE_MAX_GB`).
- `schema.py` — `row_to_judgment` maps both bucket schemas to the unified `Judgment` dataclass.
- `endpoints.py` — bucket URIs, `SCI_LANGUAGE_MAP`, HC PDF path template.

**Critical gotchas** (already encoded in the code, but easy to break in reviews):
1. With `hive_partitioning=true`, DuckDB shadows parquet columns whose names collide with partition keys. HC parquet has both a `court` column and a `court=` partition; the partition wins. **Don't add `court` back to the HC SELECT.**
2. `pdf_exists=False` in HC parquet is unreliable — bucket reality wins. **Don't pre-filter on it.**
3. SCI tar suffixes: English = 2-letter (`_EN.pdf`), regional = 3-letter (`_HIN`, `_TAM`, etc.). Use `SCI_LANGUAGE_MAP`.
4. CNR prefixes: most are `<state>HC…` but Bombay = `HCBM`, Madras = `HCMA`, Telangana = `HBHC`, Calcutta = `WBCH`. Full mapping in `courts._CNR_PREFIX_TO_COURT_CODE`.
5. `bool(0)` is `False` — never `self.x = arg or DEFAULT` if `0` is a legal value. (Bit us once with `ttl_seconds=0`.)

### CNR-prefix routing (used by the archive, useful elsewhere)

`infer_court_from_cnr(cnr)` returns a resolved `Court` from a CNR's 4-letter prefix. Verified against all 25 HC partitions + SCI in 2020. Use it before falling back to multi-source scans — `ArchiveClient.search(cnr=X)` already applies it automatically. Could be wired into the live `JudgmentSearchClient` too (not done yet).

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

- **Unit tests** (`tests/`) — 226 tests, all offline. Parser tests use HTML/JSON fixtures in `tests/fixtures/`. Archive tests use synthetic in-memory tars + `respx`-mocked HTTP.
- **Live tests** (`examples/live_test_all.py`) — 8 integration tests against real portals. Requires ddddocr. ~60% CAPTCHA accuracy with auto-retry. Archive integration verifies anonymously against both S3 buckets — no separate live-test script yet.
- **Mocking** — `respx` for HTTP (works with httpx natively), custom `CaptchaSolver` subclass returning fixed strings for live-client tests, `AsyncMock` + `unittest.mock.patch.object` for the archive query/cache layer.
- **respx caveat**: doesn't support `host__icontains` matchers — use `url__regex` instead.

## Ruff Config

Python 3.11 target, 100-char line length, rules: E, F, I, N, W. Config in `pyproject.toml`.
