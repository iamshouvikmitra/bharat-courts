# bharat-courts

> Async Python SDK for Indian court data — search cases, download orders, and access cause lists from eCourts and the Supreme Court.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/bharat-courts.svg)](https://pypi.org/project/bharat-courts/)

---

## What is this?

India's eCourts platform holds millions of case records across 25+ High Courts, 700+ District Courts, and the Supreme Court — but there's no official API. Checking case status means navigating clunky portals, solving CAPTCHAs by hand, and copy-pasting results one at a time.

**bharat-courts** fixes that. It gives you — and your AI assistant — direct programmatic access to:

- **Find any judgment with one call** — `Judgments().find(judge=..., year=..., text=..., cnr=...)` routes to the right backend (archive vs live) and returns a uniform result. The SDK does the heavy lifting; you describe the data, not where it lives.
- **Track matters** — search by case number, party name, or advocate across any High Court or District Court
- **Download orders & judgments** — get PDFs for all orders in a case with one call
- **Monitor cause lists** — see which cases are listed before which bench, every day
- **Pull recent Supreme Court judgments** — scrape the homepage's "Latest Judgements / Orders" feed and download the PDFs
- **Query the historical archive** — instant offline search across SCI judgments from 1950 and 25-HC judgments (CC-BY-4.0 AWS Open Data, no CAPTCHA, no rate limits)
- **Access District Courts** — dynamically discover courts across 36 states/UTs and search 700+ court complexes
- **Bulk download judgments** — paginate through results, batch-download PDFs with automatic session management
- **Automate CAPTCHA handling** — built-in OCR solver, ONNX solver, or plug in your own

Works standalone as a Python library, as a CLI tool, or as an **AI agent skill** — install it into Claude Code, GitHub Copilot, or any MCP-compatible assistant and ask questions in plain English.

Built for practicing lawyers, litigation teams, legal researchers, legal aid organizations, and legal tech builders.

## Installation

```bash
pip install bharat-courts

# With automatic CAPTCHA solving (recommended)
pip install bharat-courts[ocr]

# With lightweight ONNX CAPTCHA solver (alternative to ddddocr)
pip install bharat-courts[onnx]

# With CLI
pip install bharat-courts[cli]

# With historical-archive support (DuckDB over AWS Open Data buckets)
pip install bharat-courts[archive]

# Everything (OCR + ONNX + CLI + archive + dev tools)
pip install bharat-courts[all]
```

**Requires Python 3.11+**

## Use with AI agents (Claude Code, Copilot, etc.)

Install the bundled skill so your AI assistant can look up court data for you in natural language:

```bash
bharat-courts install-skills
```

Then just ask your AI agent:

> "Find all pending writ petitions for Tata Motors in Delhi High Court from 2024"

> "Download the latest order in WP(C) 4520/2023 before the Bombay High Court"

> "What's on the cause list for Karnataka High Court tomorrow?"

> "Search for cases filed by State of Bihar in Patna district court in 2024"

> "Show me the most recent Supreme Court judgments from this week"

The agent uses bharat-courts under the hood — handles CAPTCHA, sessions, and parsing automatically.

## Quick Start

### Find a judgment without picking a backend

The `Judgments` facade is the recommended entry point for "find a judgment matching some criteria" — it owns both the archive and live clients, picks the right one per query, and returns a uniform `Judgment` list. Use this unless you specifically need a portal-only feature (cause list, live case status, district-court drill-down).

```python
import asyncio
from bharat_courts import Judgments

async def main():
    async with Judgments() as j:
        # Structured filters → archive (no CAPTCHA, partition-pruned)
        for r in await j.find(judge="chandrachud", year=(2018, 2024), court="sci", limit=10):
            print(f"{r.decision_date}  {r.case_id}  {r.title}")

        # Free-text → live (only the live portal does full-text)
        for r in await j.find(text="right to privacy", limit=5):
            print(f"{r.decision_date}  {r.title}  [{r.source}]")

        # CNR alone — prefix routes to the right bucket, no full scan
        result = await j.find(cnr="DLHC010230802020")
        pdf = await j.fetch_pdf(result[0])
        with open("judgment.pdf", "wb") as f:
            f.write(pdf)

        # Force a specific backend if you need to
        archive_only = await j.find(text="bail", source="archive", limit=5)

asyncio.run(main())
```

Routing rules (see API reference for details):

| Filter shape | Backend |
|---|---|
| `cnr=` | archive (prefix → court → partition) |
| `text=` only | live (only it does full-text body search) |
| structured only (judge/party/year/court/citation) | archive |
| `text=` + structured | archive — `text` folds into a title-substring match |

Each returned `Judgment` carries a `source` field (`"archive"` or `"live"`) so consumers can still tell where it came from when that matters.

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
            print(f"  CNR: {case.cnr_number}")

asyncio.run(main())
```

### Check case status and download orders

```python
async with HCServicesClient(captcha_solver=solver) as client:
    # Look up a specific writ petition. `case_type` is the numeric code from
    # list_case_types() (e.g. "134" = W.P.(C) on Delhi HC).
    cases = await client.case_status(
        get_court("bombay"),
        case_type="134",
        case_number="4520",
        year="2023",
    )
    # case_type on the result is now a label like "W.P.(C)" (from the
    # portal's type_name field). The showRecords endpoint does not return
    # case status, so case.status is always empty.
    print(f"{cases[0].case_type} {cases[0].case_number} — CNR: {cases[0].cnr_number}")

    # Download all orders for the case
    orders = await client.court_orders(
        get_court("bombay"),
        case_type="134",
        case_number="4520",
        year="2023",
    )
    for order in orders:
        print(f"{order.order_date} — {order.order_type} by {order.judge}")
        # download_order_pdf raises RuntimeError if the portal hands back its
        # 30-byte BOM+error string instead of a real PDF.
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

### Search District Court cases

```python
from bharat_courts import DistrictCourtClient
from bharat_courts.districtcourts.parser import parse_complex_value

async with DistrictCourtClient(captcha_solver=solver) as client:
    # Discover the court hierarchy
    districts = await client.list_districts("8")        # Bihar
    complexes = await client.list_complexes("8", "1")   # Patna district

    # Parse complex value to get code + establishment info
    complex_val = list(complexes.keys())[-1]            # e.g. "1080010@2,3,4@Y"
    code, ests, needs_est = parse_complex_value(complex_val)
    est = ests[0] if needs_est else ""

    # Look up case types — the portal returns codes as "<case_type>^<est>"
    # compound strings (e.g. "89^2"); pass them back verbatim.
    case_types = await client.list_case_types("8", "1", code, est)
    # {"89^2": "ADMINISTRATIVE SUITE", "152^2": "Anticipatory Bail - ABP", ...}

    cases = await client.case_status(
        state_code="8", dist_code="1",
        court_complex_code=code, est_code=est,
        case_type="89^2",       # full compound code, not just "89"
        case_number="100", year="2024",
    )
    for case in cases:
        print(f"{case.case_number}: {case.petitioner} v {case.respondent}")
```

### List recent Supreme Court judgments

```python
from bharat_courts import SCIClient

# www.sci.gov.in surfaces the 50 most recent items inline on the homepage.
# No CAPTCHA, no search form — just scrape the feed.
async with SCIClient() as client:
    recent = await client.list_recent_judgments(limit=10)
    for j in recent:
        print(f"{j.judgment_date}: {j.title}")
        print(f"  Diary: {j.source_id}  {j.case_number}")
        # Download via /sci-get-pdf/?diary_no=... (portal viewer URL).
        await client.download_pdf(j)
        if j.pdf_bytes:
            with open(f"sci_{j.source_id}.pdf", "wb") as f:
                f.write(j.pdf_bytes)
```

(Date-range / party-name search against the legacy `main.sci.gov.in` host is no longer functional — that host is permanently 503 and the live `www.sci.gov.in` portal gates those flows behind a CAPTCHA-protected case-no/diary-no form that the SDK does not yet wire up. `search_by_year` and `search_by_party` raise `NotImplementedError`.)

### Query the historical archive (no CAPTCHA, no rate limits)

For research workloads — "find every judgment by Justice X", "all 2020 Delhi HC writ
petitions", bulk PDF retrieval — use the `ArchiveClient`, which reads the public
[AWS Open Data buckets](https://registry.opendata.aws/indian-supreme-court-judgments/)
maintained by Dattam Labs: SCI judgments from 1950 onwards and 25 High Courts.

```python
from bharat_courts import ArchiveClient

async with ArchiveClient() as client:
    # Substring match on judge, year range, partition-pruned in DuckDB.
    results = await client.search(
        court="sci", judge="chandrachud", year=(2018, 2024), limit=20,
    )
    for j in results:
        print(f"{j.decision_date}  {j.case_id}  {j.title}")
        print(f"  {j.citation}  outcome: {j.disposal_nature}")

    # Stream every Delhi 2020 judgment (~18k) without holding them all in memory.
    async for j in client.iter_judgments(court="delhi", year=2020, batch_size=500):
        process(j)

    # Fetch the PDF — CNR alone is enough; the SDK infers the source.
    pdf_bytes = await client.fetch_pdf("DLHC010230802020")
    # SCI judgments default to English; pass language="hindi" / "tamil" / etc.
    sci_pdf = await client.fetch_pdf("ESCR010000301950", language="english")
```

Notes:
- **Freshness gap**: the buckets update bi-monthly (SCI) and quarterly (HC). For
  judgments delivered in the last 2–3 months, fall back to `JudgmentSearchClient`.
- **Cache**: PDFs and parquet shards cache under `~/.cache/bharat-courts/archive/`.
  Default cap is 5 GiB (`BHARAT_COURTS_ARCHIVE_CACHE_MAX_GB`); metadata TTL is
  30 days (`BHARAT_COURTS_ARCHIVE_METADATA_TTL_DAYS`).
- **License**: data is CC-BY-4.0 — attribute Dattam Labs / the eCourts platform
  when redistributing.

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
    "case_number": "3/2024",
    "case_type": "W.P.(C)",
    "cnr_number": "DLHC010582482024",
    "filing_number": "213400000032024",
    "registration_number": "3",
    "petitioner": "HDFC BANK LTD.",
    "respondent": "UNION OF INDIA & ORS.",
    "court_name": "Delhi High Court",
    "judges": []
  }
]
```

Note: `status`, `registration_date`, `judges`, and `next_hearing_date` are not returned by the live `showRecords` endpoint and stay empty/null. They live behind the case-history endpoint which the SDK does not call yet.

## Supported Portals

| Source | Client | Status |
|--------|--------|--------|
| **Federated (archive + live)** | **`Judgments`** | **Recommended entry point — one `find()` call routes to archive vs live by query shape** |
| [HC Services](https://hcservices.ecourts.gov.in) | `HCServicesClient` | Fully working |
| [District Courts](https://services.ecourts.gov.in) | `DistrictCourtClient` | Case status, orders, cause lists across 700+ courts |
| [Judgment Search](https://judgments.ecourts.gov.in) | `JudgmentSearchClient` | Search, pagination, bulk PDF download |
| [Supreme Court](https://www.sci.gov.in) | `SCIClient` | Recent judgments feed + PDF download (case-no search not yet implemented) |
| [Calcutta High Court](https://calcuttahighcourt.gov.in) | `CalcuttaHCClient` | Order/judgment search + PDF download (direct from HC website) |
| [SCI Archive](https://registry.opendata.aws/indian-supreme-court-judgments/) (S3, CC-BY-4.0) | `ArchiveClient` | DuckDB metadata search + PDF retrieval, 1950–present; SCI bi-monthly + 25 HCs quarterly |
| [HC Archive](https://registry.opendata.aws/indian-high-court-judgments/) (S3, CC-BY-4.0) | `ArchiveClient` | Same as above; routed via the unified `ArchiveClient` |

## API Reference

### `Judgments` (federated facade)

The recommended entry point for finding judgments. Owns an `ArchiveClient` and a `JudgmentSearchClient` internally (lazy-initialised), picks the right backend per query, and returns a uniform `list[Judgment]`. Reach for the portal-specific clients only when you need something the facade doesn't expose (cause lists, case status, district-court drill-down).

```python
from bharat_courts import Judgments

async with Judgments() as j:
    ...
```

No new install extra — pulls in whatever backends are available. For best behaviour install both:

```bash
pip install 'bharat-courts[archive,ocr]'
```

---

#### `find(*, text=None, court=None, year=None, judge=None, party=None, citation=None, cnr=None, source="auto", limit=50) -> list[Judgment]`

Run a search, routing transparently between the archive and the live portal.

| Parameter | Type | Description |
|-----------|------|-------------|
| `text` | `str \| None` | Free-text keyword search. Routes to live (only the live judgments portal does full-body search). |
| `court` | `Court \| str \| None` | Court object or code (`"sci"`, `"delhi"`). |
| `year` | `int \| tuple[int, int] \| None` | Single year or inclusive range. Drives archive partition pruning — strongly recommended for non-CNR queries. |
| `judge` | `str \| None` | Substring on the judge field (archive). |
| `party` | `str \| None` | Substring on petitioner/respondent (SCI) or title (HC). |
| `citation` | `str \| None` | Citation substring (archive, SCI only). |
| `cnr` | `str \| None` | Exact CNR match. Auto-routes via the 4-letter prefix when `source="auto"`. |
| `source` | `"auto" \| "archive" \| "live"` | Override the automatic routing. |
| `limit` | `int` | Total results to return (default 50). |

**Returns:** `list[Judgment]` with `source` set to `"archive"` or `"live"` per item.

**Routing (in `source="auto"` mode):**

| filter shape | backend |
|---|---|
| `cnr=` set | archive (prefix-routed; no scan) |
| `text=` set, no structured filters | live |
| structured filters only (court/year/judge/party/citation) | archive |
| `text=` + structured filters | archive — `text` folds into a title-substring match (party slot) |
| nothing | raises `ValueError` |

The decision is logged at INFO level (`logging.getLogger("bharat_courts.facade")`).

---

#### `fetch_pdf(judgment_or_cnr, *, language="english") -> bytes`

Convenience wrapper that delegates to `ArchiveClient.fetch_pdf`. Accepts a `Judgment` instance or a CNR string. Raises `NotImplementedError` if you pass a `Judgment` with `source="live"` — the live download path needs the original `JudgmentResult` (for session continuity), so call `JudgmentSearchClient.download_pdf(judgment_result, court_type)` directly for that case.

---

#### `live_to_judgment(jr: JudgmentResult) -> Judgment`

Public helper if you're doing routing yourself: normalises a `JudgmentResult` (returned by `JudgmentSearchClient.search`) into the unified `Judgment` shape. Maps `source_id → cnr`, resolves `court_name` via the registry, pulls `disposal_nature` / `registration_date` out of `metadata`.

---

### `HCServicesClient`

Primary client for High Court case data via `hcservices.ecourts.gov.in`.

```python
from bharat_courts import HCServicesClient

client = HCServicesClient(
    config=None,            # BharatCourtsConfig | None — uses global config singleton if None
    captcha_solver=None,    # CaptchaSolver | None — defaults to OCRCaptchaSolver if ddddocr installed
    http_client=None,       # RateLimitedClient | None — creates one internally if None
)
```

Use as an async context manager (no solver needed if `bharat-courts[ocr]` is installed):

```python
async with HCServicesClient() as client:
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

Look up case status by case number. **CAPTCHA required** (auto-retried, default 5 attempts).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `court` | `Court` | Yes | — | Court object |
| `case_type` | `str` | Yes | — | Numeric case type code (use `list_case_types()` to discover) |
| `case_number` | `str` | Yes | — | Case number without type/year |
| `year` | `str` | Yes | — | Registration year, e.g. `"2024"` |
| `bench_code` | `str` | No | `"1"` | Bench code from `list_benches()` |

**Returns:** `list[CaseInfo]` — matching cases. Notable field semantics:

- `case_type` on the result is a **label** like `"W.P.(C)"` (sourced from the portal's `type_name` field), not the numeric code you passed in.
- `registration_number` is populated from the portal's `case_no2` field.
- `status` is **always empty** — the live `showRecords` endpoint doesn't return Pending/Disposed (that data lives behind `o_civil_case_history.php`, which the SDK doesn't call yet). Same for `registration_date`, `judges`, and `next_hearing_date`.

```python
cases = await client.case_status(
    delhi,
    case_type="134",      # numeric code from list_case_types()
    case_number="1",
    year="2024",
)
for case in cases:
    print(f"{case.case_type} {case.case_number}  CNR: {case.cnr_number}")
    print(f"  {case.petitioner} v {case.respondent}")
```

---

#### `case_status_by_party(court, *, party_name, year, bench_code="1", status_filter="Both") -> list[CaseInfo]`

Search cases by party name. **CAPTCHA required** (auto-retried, default 5 attempts).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `court` | `Court` | Yes | — | Court object |
| `party_name` | `str` | Yes | — | Petitioner or respondent name (min 3 characters) |
| `year` | `str` | Yes | — | Registration year — **mandatory**, server returns error if empty |
| `bench_code` | `str` | No | `"1"` | Bench code |
| `status_filter` | `str` | No | `"Both"` | `"Pending"`, `"Disposed"`, or `"Both"` (forwarded to the portal — but the response carries no status field, so filtering happens server-side and the returned `CaseInfo.status` is still empty) |

**Returns:** `list[CaseInfo]` — matching cases. Same field-population caveats as `case_status` above. Wide queries can return tens of thousands of records in a single response with no pagination — see [issue tracker](https://github.com/iamshouvikmitra/bharat-courts/issues).

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

**Raises:** `RuntimeError` if the response doesn't start with the `%PDF` magic bytes. The HC Services portal sometimes hands back a 30-byte BOM-prefixed `"Unable to connect to server"` string with HTTP 200; this method now refuses to silently return that as a PDF.

```python
pdf_bytes = await client.download_order_pdf(order.pdf_url)
with open("order.pdf", "wb") as f:
    f.write(pdf_bytes)
```

---

### `DistrictCourtClient`

Client for District Courts across India via `services.ecourts.gov.in`. Covers 700+ court complexes across 36 states/UTs.

Unlike High Courts (which use static `get_court()` codes), district courts require dynamic discovery of the 4-level hierarchy: **State → District → Court Complex → Establishment**.

```python
from bharat_courts import DistrictCourtClient

client = DistrictCourtClient(
    config=None,            # BharatCourtsConfig | None
    captcha_solver=None,    # CaptchaSolver | None — defaults to OCRCaptchaSolver if ddddocr installed
    http_client=None,       # RateLimitedClient | None
)
```

Use as an async context manager:

```python
async with DistrictCourtClient() as client:
    ...
```

---

#### Court Discovery Methods (No CAPTCHA)

These methods discover the court hierarchy dynamically.

##### `list_states() -> dict[str, str]`

Returns all 36 states/UTs with their codes. Static data, no network call.

```python
states = await client.list_states()
# {"8": "Bihar", "7": "Delhi", "27": "Maharashtra", ...}
```

##### `list_districts(state_code) -> dict[str, str]`

Get districts for a state.

```python
districts = await client.list_districts("8")  # Bihar
# {"1": "Patna", "35": "Gaya", "38": "Muzaffarpur", ...}
```

##### `list_complexes(state_code, dist_code) -> dict[str, str]`

Get court complexes for a district. Values are in `code@ests@flag` format.

```python
complexes = await client.list_complexes("8", "1")  # Bihar, Patna
# {"1080010@2,3,4@Y": "Civil Court, Patna Sadar", ...}

# Parse the value to extract the code and check if establishment selection is needed
from bharat_courts.districtcourts.parser import parse_complex_value
code, est_codes, needs_est = parse_complex_value("1080010@2,3,4@Y")
# code="1080010", est_codes=["2","3","4"], needs_est=True
```

##### `list_establishments(state_code, dist_code, court_complex_code) -> dict[str, str]`

Get establishments for a court complex. Only needed when `needs_est` is `True`.

```python
establishments = await client.list_establishments("8", "1", "1080010")
# {"2": "DJ Div. Patna Sadar", "3": "CJM Div. Patna Sadar", ...}
```

##### `list_case_types(state_code, dist_code, court_complex_code, est_code) -> dict[str, str]`

Get available case types for a court. Codes are returned in the portal's compound `"<case_type>^<est_code>"` format — pass them back **verbatim** to `case_status` / `court_orders`; do not strip the `^N` suffix.

```python
case_types = await client.list_case_types("8", "1", "1080010", "2")
# {"89^2": "ADMINISTRATIVE SUITE", "152^2": "Anticipatory Bail - ABP", ...}
```

##### `list_cause_list_courts(state_code, dist_code, court_complex_code, est_code="") -> dict[str, str]`

Get the courts dropdown for cause-list lookup. Returns a mapping of `court_no` (e.g. `"1@2"`) to court display name (e.g. `"District & Sessions Judge - DJ Div. Patna Sadar"`). The cause-list form requires both — pass either through directly to `cause_list()`, which will look up the matching name automatically if you only know the code.

```python
courts = await client.list_cause_list_courts("8", "1", "1080010", "2")
# {"1@2": "District & Sessions Judge - DJ Div. Patna Sadar", ...}
```

---

#### Search Methods (CAPTCHA Required)

All search methods take the 4-level court identifiers as keyword arguments.

##### `case_status(*, state_code, dist_code, court_complex_code, est_code, case_type, case_number, year) -> list[CaseInfo]`

Search by case number. `case_type` must be the full compound `"<code>^<est>"` string from `list_case_types()`.

```python
cases = await client.case_status(
    state_code="8", dist_code="1",
    court_complex_code="1080010", est_code="2",
    case_type="89^2",      # full compound code, not just "89"
    case_number="100", year="2024",
)
```

##### `case_status_by_party(*, state_code, dist_code, court_complex_code, est_code, party_name, year, status_filter="Both") -> list[CaseInfo]`

Search by party name (min 3 characters). `year` is mandatory.

```python
cases = await client.case_status_by_party(
    state_code="8", dist_code="1",
    court_complex_code="1080010", est_code="2",
    party_name="kumar", year="2024",
    status_filter="Pending",   # "Pending", "Disposed", or "Both"
)
```

##### `court_orders(*, state_code, dist_code, court_complex_code, est_code, case_type, case_number, year) -> list[CaseOrder]`

Get court orders for a case.

```python
orders = await client.court_orders(
    state_code="8", dist_code="1",
    court_complex_code="1080010", est_code="2",
    case_type="1", case_number="100", year="2024",
)
```

##### `cause_list(*, state_code, dist_code, court_complex_code, est_code, court_no, court_name="", causelist_date="", civil=True) -> list[CauseListEntry]`

Get cause list entries. `court_no` is now **required** — discover the available codes via `list_cause_list_courts()`. `court_name` is the option's display label; the portal validates against it (sending an empty `court_name_txt` triggers a `"Court Name is required"` error). If you leave `court_name` blank, this method calls `list_cause_list_courts()` once and looks up the matching label for `court_no`.

```python
entries = await client.cause_list(
    state_code="8", dist_code="1",
    court_complex_code="1080010", est_code="2",
    court_no="1@2",                # required, from list_cause_list_courts()
    civil=True,
    causelist_date="20-03-2026",   # DD-MM-YYYY, defaults to today
)
for e in entries:
    print(f"#{e.serial_number} {e.case_number} — {e.petitioner} v {e.respondent}")
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

#### `search(search_text, *, page=1, page_size=10, search_opt="PHRASE", court_type="2", max_captcha_attempts=5) -> SearchResult`

Search for judgments by keyword. **CAPTCHA required.**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `search_text` | `str` | Yes | — | Search query text |
| `page` | `int` | No | `1` | Page number (1-indexed) |
| `page_size` | `int` | No | `10` | Rows per page (portal supports 10/25/50/100/1000) |
| `search_opt` | `str` | No | `"PHRASE"` | `"PHRASE"`, `"ANY"`, or `"ALL"` |
| `court_type` | `str` | No | `"2"` | `"2"` for High Courts, `"3"` for SCR |
| `max_captcha_attempts` | `int` | No | `5` | Max CAPTCHA retry attempts |

**Returns:** `SearchResult` — contains `items: list[JudgmentResult]`, `total_count`, pagination info. Each `JudgmentResult` includes parsed metadata (CNR number, disposal nature, registration date) and `source_id` (CNR) when available.

**Raises:** `CaptchaError` if the CAPTCHA solver couldn't authenticate within `max_captcha_attempts` tries. Empty results now mean "the portal returned zero rows" — they no longer mask a silent CAPTCHA failure (older versions returned `SearchResult()` with no signal).

```python
from bharat_courts import JudgmentSearchClient
from bharat_courts.captcha.ocr import OCRCaptchaSolver

async with JudgmentSearchClient(captcha_solver=OCRCaptchaSolver()) as client:
    results = await client.search("right to privacy")
    print(f"Found {results.total_count} results")
    for judgment in results.items:
        print(f"{judgment.title}")
        print(f"  Court: {judgment.court_name}, Date: {judgment.judgment_date}")
        print(f"  CNR: {judgment.source_id}")
        print(f"  Metadata: {judgment.metadata}")
```

---

#### `search_all(search_text, *, page_size=25, search_opt="PHRASE", court_type="2", max_captcha_attempts=5) -> AsyncIterator[SearchResult]`

Iterate through all pages of search results. Yields one `SearchResult` per page, automatically handling pagination, token rotation, and session expiry (re-authenticates mid-walk if the portal session lapses).

```python
async with JudgmentSearchClient(captcha_solver=solver) as client:
    async for page in client.search_all("land acquisition"):
        for judgment in page.items:
            print(f"{judgment.title} ({judgment.judgment_date})")
```

---

#### `download_pdf(judgment, *, court_type="2") -> JudgmentResult`

Download the PDF for a judgment result.

Important: `judgment.pdf_url` is **not** a directly-fetchable URL — it's the row's relative `path` from the portal's `open_pdf(...)` JS handler. This method does the `openpdfcaptcha` resolution dance to obtain a per-session `outputfile` URL, then GETs the actual PDF bytes. Each row's `pdf_val` (also stashed by the parser inside `judgment.metadata`) is forwarded automatically; without it the portal serves the first row's PDF for every subsequent call within the same session.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `judgment` | `JudgmentResult` | Yes | — | A result from `search()` |
| `court_type` | `str` | No | `"2"` | Same `"2"` / `"3"` as on `search()` |

**Returns:** the same `JudgmentResult` mutated in place — `pdf_bytes` is set on success.

**Raises:** `RuntimeError` if the response is empty, non-JSON, or doesn't start with `%PDF`.

```python
judgment = results.items[0]
await client.download_pdf(judgment)
if judgment.pdf_bytes:
    with open("judgment.pdf", "wb") as f:
        f.write(judgment.pdf_bytes)
```

---

#### `download_pdfs(judgments, *, court_type="2", stop_on_error=False) -> list[JudgmentResult]`

Bulk-download PDFs for multiple judgments. Skips entries that already have `pdf_bytes` set. Failed downloads are logged at WARNING level by default; pass `stop_on_error=True` to raise on the first failure instead.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `judgments` | `list[JudgmentResult]` | Yes | — | Judgments to download PDFs for |
| `court_type` | `str` | No | `"2"` | Forwarded to each `download_pdf` call |
| `stop_on_error` | `bool` | No | `False` | Re-raise the first download exception instead of logging it |

**Returns:** the same list, with `pdf_bytes` populated where successful.

```python
async with JudgmentSearchClient(captcha_solver=solver) as client:
    results = await client.search("constitution")
    await client.download_pdfs(results.items)
    for j in results.items:
        if j.pdf_bytes:
            with open(f"{j.case_number}.pdf", "wb") as f:
                f.write(j.pdf_bytes)
```

---

### `SCIClient`

Client for the Supreme Court of India (`www.sci.gov.in`). **No CAPTCHA required.**

The legacy host (`main.sci.gov.in`) that older versions of this SDK targeted has been in long-term maintenance for years and now returns HTTP 503 to every path. The live site is `www.sci.gov.in` (WordPress); `SCIClient` was rewritten against it.

```python
from bharat_courts import SCIClient

# Note: no captcha_solver parameter — the homepage feed doesn't use CAPTCHAs
async with SCIClient() as client:
    ...
```

---

#### `list_recent_judgments(*, limit=50) -> list[JudgmentResult]`

Scrape the homepage's "Latest Judgements / Orders" feed. Returns the 50 most recent items the portal surfaces inline (the portal caps it at 50 — pass a smaller `limit` to truncate).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | `int` | No | `50` | Max items to return |

**Returns:** `list[JudgmentResult]` — each carries:

- `title` — `"PETITIONER VS. RESPONDENT"`
- `case_number` — e.g. `"C.A. No. 6677/2026"`
- `judgment_date` — parsed from the row's "DD-MMM-YYYY" tail
- `source_id` — diary number (the portal's primary key)
- `pdf_url` — the `/sci-get-pdf/?diary_no=...` URL the in-page viewer iframe uses
- `source_url` — the matching `/view-pdf/?diary_no=...` URL (for opening in a browser)
- `metadata["petitioner"]`, `metadata["respondent"]`, `metadata["type"]` (`"j"` = judgment, `"o"` = order)

```python
async with SCIClient() as client:
    recent = await client.list_recent_judgments(limit=10)
    for j in recent:
        print(f"{j.judgment_date}: {j.title}  [diary {j.source_id}]")
```

---

#### `download_pdf(judgment) -> JudgmentResult`

Download the PDF bytes for a Supreme Court judgment via the `/sci-get-pdf/?diary_no=...` endpoint.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `judgment` | `JudgmentResult` | Yes | An item from `list_recent_judgments()` |

**Returns:** the same `JudgmentResult` with `pdf_bytes` populated.

**Raises:** `RuntimeError` if the response doesn't start with `%PDF`.

---

#### `search_by_year(year, month=None)` and `search_by_party(party_name)` — not implemented

Both methods now raise `NotImplementedError`. The legacy `main.sci.gov.in` form they hit is permanently 503; the equivalent flow on `www.sci.gov.in` is gated behind a CAPTCHA-protected case-no/diary-no/party-name form (`/judgements-case-no/`) that the SDK does not yet wire up. Use `list_recent_judgments()` for the most recent items.

---

### `CalcuttaHCClient`

Client for Calcutta High Court's own website (`calcuttahighcourt.gov.in`). Provides order/judgment search with PDF download for cases from September 2020 onwards (CIS system). Has better PDF coverage than the eCourts portal for Calcutta HC cases.

```python
from bharat_courts import CalcuttaHCClient

async with CalcuttaHCClient() as client:
    ...
```

---

#### `search_orders(*, case_type, case_number, year, establishment="appellate", max_captcha_attempts=5) -> tuple[CaseInfo | None, list[CaseOrder]]`

Search for orders/judgments by case number. **CAPTCHA required** (auto-retried, default 5 attempts).

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `case_type` | `str` | Yes | — | Numeric case type code (e.g. `"12"` for WPA) |
| `case_number` | `str` | Yes | — | Case registration number |
| `year` | `str` | Yes | — | Case year |
| `establishment` | `str` | No | `"appellate"` | `"appellate"`, `"original"`, `"jalpaiguri"`, or `"portblair"` |
| `max_captcha_attempts` | `int` | No | `5` | Max CAPTCHA retries |

**Returns:** `tuple[CaseInfo | None, list[CaseOrder]]`. The `CaseInfo` carries the case-level metadata the portal returns alongside the order rows (parties, CNR, full case number, side); previous versions silently dropped this. Returns `(None, [])` when nothing matched.

```python
case_info, orders = await client.search_orders(
    case_type="12",        # WPA
    case_number="12886",
    year="2024",
    establishment="appellate",
)
if case_info:
    print(f"{case_info.case_number}  CNR: {case_info.cnr_number}")
    print(f"  {case_info.petitioner} v {case_info.respondent}")
for order in orders:
    print(f"{order.order_date}: {order.order_type} by {order.judge}")
    print(f"  Neutral Citation: {order.neutral_citation}")
    if order.pdf_url:
        pdf = await client.download_order_pdf(order.pdf_url)
```

---

#### `download_order_pdf(pdf_url) -> bytes`

Download an order/judgment PDF. **No CAPTCHA required.**

**Raises:** `RuntimeError` if the response doesn't start with the `%PDF` magic bytes.

```python
pdf_bytes = await client.download_order_pdf(order.pdf_url)
```

---

### `ArchiveClient`

Read-only access to the public AWS Open Data judgment archives (no CAPTCHA, no
rate limits, no accounts). Requires the `archive` extra:

```bash
pip install 'bharat-courts[archive]'
```

```python
from bharat_courts import ArchiveClient

async with ArchiveClient(
    cache_dir=None,          # str | None — defaults to ~/.cache/bharat-courts/archive/
    cache_max_bytes=None,    # int | None — defaults to 5 GiB (or env override)
    metadata_cache=True,     # bool — disable to skip the local parquet mirror
) as client:
    ...
```

DuckDB runs the metadata queries against partitioned parquet files; PDFs are
served via direct HTTP GET (HC, one file per judgment) or random-access tar
extraction (SCI, one tar per year). Both layers cache on disk.

---

#### `search(*, court=None, year=None, judge=None, party=None, citation=None, cnr=None, limit=50) -> list[Judgment]`

Search both archives in one call. CNR-only queries auto-route via the prefix —
no need to specify `court=` for `fetch_pdf("DLHC...")`.

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `court` | `Court \| str \| None` | No | `None` | Court object, code string (`"sci"`, `"delhi"`), or `None` to query both buckets |
| `year` | `int \| tuple[int, int] \| None` | No | `None` | Single year (`2020`) or inclusive range (`(2018, 2024)`). Drives partition pruning — strongly recommended for non-CNR queries |
| `judge` | `str \| None` | No | `None` | Case-insensitive substring on the judge field |
| `party` | `str \| None` | No | `None` | SCI: searches petitioner/respondent/title. HC: title only (HC parquet has no party columns) |
| `citation` | `str \| None` | No | `None` | SCI only — silently ignored for HC |
| `cnr` | `str \| None` | No | `None` | Exact CNR match. Auto-resolves source from the 4-letter prefix when `court` isn't given |
| `limit` | `int` | No | `50` | Total results across sources |

**Returns:** `list[Judgment]` sorted by `decision_date DESC`.

---

#### `iter_judgments(*, court=None, year=None, judge=None, party=None, citation=None, cnr=None, batch_size=500, max_results=None) -> AsyncIterator[Judgment]`

Stream judgments page-by-page via `LIMIT/OFFSET` with a stable sort
(`decision_date DESC, cnr`). Use this for bulk pulls — "all 18k Delhi 2020
judgments" — without materialising everything in memory.

Sources are streamed sequentially (SCI first, then HC) with no cross-source
date merge.

```python
count = 0
async for j in client.iter_judgments(court="delhi", year=2020, batch_size=500):
    count += 1
    # process(j)
```

---

#### `fetch_pdf(judgment_or_cnr, *, language="english") -> bytes`

Fetch a judgment PDF. Pass a `Judgment` (preferred — avoids a metadata lookup)
or a CNR string. SCI judgments support `language="hindi" | "tamil" | "gujarati" | …`
(see `bharat_courts.archive.endpoints.SCI_LANGUAGE_MAP`); HC PDFs are
English-only in the archive.

```python
data = await client.fetch_pdf("DLHC010230802020")        # ~250 KB direct GET
data = await client.fetch_pdf("ESCR010000301950", language="english")
# First SCI fetch in a year downloads the year tar (~40–500 MB); subsequent
# fetches for that year are tar-extraction-fast.
```

**Raises:** `ArchivePdfError` for missing files, missing metadata fields, or
HTTP failures.

---

#### `prefetch_sci_year(year, language="english") -> str`

Pre-warm the SCI tar cache for a year. Useful before a batch of related
fetches.

---

#### `count(*, court=None, year=None) -> dict[str, int]`

Per-bucket row counts, e.g. `{"sci": 571}` for a single SCI year.

---

#### `cache_info() -> dict`

Snapshot: `{"cache_dir": ..., "files": ..., "bytes": ..., "max_bytes": ...}`.

---

#### Helpers

```python
from bharat_courts import infer_court_from_cnr

infer_court_from_cnr("DLHC010230802020")  # → Court(code="delhi", ...)
infer_court_from_cnr("ESCR010000301950")  # → SUPREME_COURT
infer_court_from_cnr("ZZZZ012345")        # → None
```

Use this if you're routing CNRs yourself (e.g. into the live `JudgmentSearchClient`).

---

### Court Registry Functions

```python
from bharat_courts import get_court, get_court_by_name, list_high_courts, list_all_courts
from bharat_courts.courts import get_court_by_judgment_code
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

#### `get_court_by_judgment_code(judgment_code) -> Court | None`

Look up a court by its `judgments.ecourts.gov.in` code. Returns the main court (not bench variants).

```python
get_court_by_judgment_code("7")   # Delhi High Court
get_court_by_judgment_code("27")  # Bombay High Court (main, not bench)
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
    state_code: str             # "26" (hcservices.ecourts.gov.in)
    court_type: CourtType       # CourtType.HIGH_COURT
    bench: str | None = None    # "Lucknow Bench" (for bench-specific entries)
    judgment_code: str = ""     # "7" (judgments.ecourts.gov.in)

    @property
    def slug(self) -> str               # code lowercased, spaces replaced with hyphens
    @property
    def judgment_compound_code(self) -> str  # "{judgment_code}~{state_code}", e.g. "7~26"
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
    case_type: str                          # Case type label, e.g. "W.P.(C)"
    cnr_number: str = ""                    # "DLHC010582482024"
    filing_number: str = ""
    registration_number: str = ""
    registration_date: date | None = None
    petitioner: str = ""
    respondent: str = ""
    status: str = ""                        # empty for HC Services (showRecords doesn't return it)
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
    neutral_citation: str = ""  # e.g. "2024:CHC-AS:1277" (Calcutta HC)
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

Returned by `JudgmentSearchClient.search()` / `search_all()` and `SCIClient.list_recent_judgments()`.

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

~75% accuracy on the judgments portal in our measurements; failed attempts are automatically retried with fresh sessions (default 5 retries — `P(all fail) ≈ 0.1%`). Outputs that aren't exactly 6 alphanumeric characters are rejected before being submitted, so the portal's "captcha must be 6 chars" envelope no longer burns a retry.

#### `ONNXCaptchaSolver`

Lightweight CAPTCHA solver using ONNX Runtime. Requires `pip install bharat-courts[onnx]`. Uses a pre-trained model from HuggingFace (captchabreaker), downloaded to `~/.cache/bharat-courts/` at init time.

**Requires `HF_TOKEN`**: The HuggingFace model repo requires authentication. Set `export HF_TOKEN=hf_...` (get a token at https://huggingface.co/settings/tokens). If you don't have a token, use `OCRCaptchaSolver` instead.

```python
from bharat_courts.captcha.onnx import ONNXCaptchaSolver

solver = ONNXCaptchaSolver()

# Or with a custom model file
solver = ONNXCaptchaSolver(model_path="/path/to/custom_model.onnx")
```

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `model_path` | `str \| Path \| None` | No | `None` | Path to a custom ONNX model. If `None`, downloads the default captchabreaker model. |

Validates that decoded text is exactly 6 characters — returns empty string on wrong length to trigger client retry.

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

The CLI is organised into one command group per portal, matching the SDK module layout:

```
bharat-courts version
bharat-courts courts [--type all|hc|sc]
bharat-courts find             [--text | --judge | --party | --citation | --cnr | --court | --year | --source]
bharat-courts hcservices       benches | case-types | search | search-by-party | orders | cause-list
bharat-courts districtcourts   states | districts | complexes | establishments | case-types | courts | search | search-by-party | orders | cause-list
bharat-courts calcuttahc       search
bharat-courts judgments        search | search-all
bharat-courts sci              recent
bharat-courts archive          query | get | download | count | cache
bharat-courts install-skills
```

The top-level `find` command is the federated entry point: it routes between archive and live based on which filters you pass. Use it as the default for "find a judgment"; reach for the portal-specific groups when you need a portal-only feature.

Global flags (apply to every subcommand):

| Flag | Description |
|------|-------------|
| `--json` | Emit machine-readable JSON instead of formatted text. Lists return arrays; single dataclasses return objects; `calcuttahc search` returns `{"case_info": ..., "orders": [...]}`. |
| `--captcha-attempts N` | Override the default CAPTCHA retry budget (5). Currently honoured by `judgments` and `calcuttahc`; `hcservices` and `districtcourts` use a fixed internal budget. |
| `--verbose` / `-v` | Enable INFO-level SDK logging on stderr. |

Every PDF-producing command takes `--download DIR` to save PDFs alongside the printed output. Filenames are `<case_or_title>_<date>.pdf`, sanitised.

### Examples

```bash
# Print version, list available courts
bharat-courts version
bharat-courts courts --type hc

# Federated find — routes between archive and live for you
bharat-courts find --judge "chandrachud" --year 2022 --court sci --limit 5
bharat-courts find --cnr DLHC010230802020              # auto-routed via CNR prefix
bharat-courts find --text "right to privacy" --limit 5  # → live (full-text)
bharat-courts find --text "asian hotels" --court delhi --year 2020  # mixed → archive
bharat-courts find --party "tata motors" --year 2020 --source archive  # force backend
bharat-courts --json find --judge "bobde" --year 2020 --court sci  # JSON output

# HC Services — discover bench / case-type codes, then search
bharat-courts hcservices benches delhi
bharat-courts hcservices case-types delhi --bench 1
bharat-courts hcservices search delhi --case-type 134 --case-number 1 --year 2024
bharat-courts hcservices orders delhi --case-type 134 --case-number 1 --year 2024 --download ./orders/
bharat-courts hcservices cause-list delhi --date 24-04-2026

# District Courts — drill down state -> district -> complex -> establishment
bharat-courts districtcourts states
bharat-courts districtcourts districts --state 8
bharat-courts districtcourts complexes --state 8 --dist 1
bharat-courts districtcourts case-types --state 8 --dist 1 --complex 1080010 --est 2
bharat-courts districtcourts search \
    --state 8 --dist 1 --complex 1080010 --est 2 \
    --case-type "89^2" --case-number 100 --year 2024
bharat-courts districtcourts cause-list \
    --state 8 --dist 1 --complex 1080010 --est 2 \
    --court-no "1@2"   # --court-name auto-resolves if blank

# Calcutta HC (returns case_info + orders)
bharat-courts calcuttahc search --case-type 12 --case-number 12886 --year 2024

# Judgments portal
bharat-courts judgments search --text "right to privacy" --page-size 25
bharat-courts judgments search-all --text "land acquisition" --max-pages 5 --download ./pdfs/

# Supreme Court — homepage feed
bharat-courts sci recent --limit 10
bharat-courts sci recent --limit 5 --download ./sci-pdfs/

# Historical archive (AWS Open Data buckets — needs `pip install bharat-courts[archive]`)
bharat-courts archive query --court sci --judge "chandrachud" --year 2022 --limit 5
bharat-courts archive query --court delhi --year 2020 --judge endlaw --limit 3
bharat-courts archive get --cnr DLHC010230802020 --pdf --out ./judgment.pdf
bharat-courts archive download --court sci --year 2020   # pre-warm the year tar
bharat-courts archive count --court sci --year 2020      # → "sci: 571"
bharat-courts archive cache                              # show disk usage
bharat-courts archive cache --clear                      # wipe local cache

# JSON output for piping to jq / spreadsheets
bharat-courts --json courts --type sc | jq '.[].name'
bharat-courts --json hcservices benches bombay
bharat-courts --json archive query --court sci --year 2020 --judge bobde --limit 10

# Install the AI agent skill bundle (Claude Code, Copilot, etc.)
bharat-courts install-skills
```

## Configuration

Environment variables with `BHARAT_COURTS_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `BHARAT_COURTS_REQUEST_DELAY` | `1.0` | Seconds between requests |
| `BHARAT_COURTS_TIMEOUT` | `60` | Request timeout (seconds). Wide District Courts party-name searches genuinely take 30-60s on the portal — the previous default of 30 was too tight and triggered timeouts against endpoints that were about to respond. |
| `BHARAT_COURTS_MAX_RETRIES` | `3` | Retry count on failure (only applied to 5xx and connect/read timeouts; 4xx responses propagate immediately). |
| `BHARAT_COURTS_LOG_LEVEL` | `INFO` | Logging level |

Or use a `.env` file. See [.env.example](.env.example).

## Supported Courts

All 25 High Courts with verified eCourts state codes and judgment portal codes:

| Court | Code | State Code | Judgment Code |
|-------|------|------------|---------------|
| Allahabad HC | `allahabad` | 13 | 9 |
| Andhra Pradesh HC | `andhra` | 2 | 28 |
| Bombay HC | `bombay` | 1 | 27 |
| Calcutta HC | `calcutta` | 16 | 19 |
| Chhattisgarh HC | `chhattisgarh` | 18 | 22 |
| Delhi HC | `delhi` | 26 | 7 |
| Gauhati HC | `gauhati` | 6 | 18 |
| Gujarat HC | `gujarat` | 17 | 24 |
| Himachal Pradesh HC | `himachal` | 5 | 2 |
| J&K HC | `jammu` | 12 | 1 |
| Jharkhand HC | `jharkhand` | 7 | 20 |
| Karnataka HC | `karnataka` | 3 | 29 |
| Kerala HC | `kerala` | 4 | 32 |
| Madhya Pradesh HC | `mp` | 23 | 23 |
| Madras HC | `madras` | 10 | 33 |
| Manipur HC | `manipur` | 25 | 14 |
| Meghalaya HC | `meghalaya` | 21 | 17 |
| Orissa HC | `orissa` | 11 | 21 |
| Patna HC | `patna` | 8 | 10 |
| Punjab & Haryana HC | `punjab` | 22 | 3 |
| Rajasthan HC | `rajasthan` | 9 | 8 |
| Sikkim HC | `sikkim` | 24 | 11 |
| Telangana HC | `telangana` | 29 | 36 |
| Tripura HC | `tripura` | 20 | 16 |
| Uttarakhand HC | `uttarakhand` | 15 | 5 |
| Supreme Court | `sci` | 0 | — |

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
pytest                                    # 250 unit tests, no network needed
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
python tests/integration/hcservices.py    # live HC Services + CAPTCHA solver
python tests/integration/archive.py       # archive + facade against real S3
# see tests/integration/README.md for the full list
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
│   ├── ocr.py           # ddddocr-based solver
│   └── onnx.py          # ONNX Runtime solver (captchabreaker)
├── hcservices/          # HC Services portal (primary, fully working)
│   ├── client.py        # HCServicesClient
│   ├── endpoints.py     # URL + form builders
│   └── parser.py        # JSON + HTML response parsers
├── districtcourts/      # District Courts portal (700+ courts)
│   ├── client.py        # DistrictCourtClient
│   ├── endpoints.py     # URL + form builders + state codes
│   └── parser.py        # HTML response parsers
├── calcuttahc/          # Calcutta High Court (direct website)
│   ├── client.py        # CalcuttaHCClient
│   ├── endpoints.py     # URL + form builders
│   └── parser.py        # JSON + HTML response parsers
├── judgments/            # Judgment Search portal (basic)
│   ├── client.py
│   ├── endpoints.py
│   └── parser.py
├── sci/                 # Supreme Court (basic)
│   ├── client.py
│   └── parser.py
├── archive/             # AWS Open Data archive (opt-in via [archive] extra)
│   ├── client.py        # ArchiveClient — async facade
│   ├── endpoints.py     # Bucket URIs + SCI language map
│   ├── metadata.py      # DuckDB query layer over partitioned parquet
│   ├── metadata_cache.py# Local mirror of parquet shards (TTL-invalidated)
│   ├── schema.py        # Row → Judgment mapping (handles SCI + HC schemas)
│   └── storage.py       # PDF cache (per-tar SCI, per-file HC) + LRU eviction
├── facade.py            # Judgments — federated find()/fetch_pdf, routes archive vs live
└── cli.py               # Click CLI entry point
```

### Areas where help is needed

- **Better CAPTCHA solving** — ddddocr is ~75% accurate on the judgments portal; the ONNX solver is an alternative, but a fine-tuned model would help further
- **District court search reliability** — `case_status`, `court_orders`, and `cause_list` were rewired this cycle to send the right portal field names; broader coverage testing would surface remaining edge cases (and `case_status_by_party` still has no pagination)
- **Supreme Court case search** — `SCIClient.search_by_year` / `search_by_party` are stubbed; the live `www.sci.gov.in` portal has a CAPTCHA-protected case-no/diary-no/party-name form that needs wiring up
- **HC Services case history** — `case_status` doesn't return Pending/Disposed (or registration date / next hearing) because the SDK hits `showRecords` only; calling `o_civil_case_history.php` afterwards would fill in the rest
- **More High Court coverage** — test the client against courts beyond Delhi/Bombay/Allahabad
- **Documentation** — more examples, tutorials

### Submitting changes

1. Fork the repo and create a branch (`git checkout -b my-feature`)
2. Make your changes
3. Run `pytest` and `ruff check .` to ensure tests pass and code is clean
4. Commit with a descriptive message
5. Open a pull request

## How it works

### HC Services Portal

The eCourts HC Services portal (`hcservices.ecourts.gov.in`) uses a PHP backend with:

1. **Session cookies** — `GET main.php` establishes `HCSERVICES_SESSID`
2. **Securimage CAPTCHAs** — pinned to the session (same image within one session)
3. **AJAX POST requests** — `cases_qry/index_qry.php` with `action_code` parameter
4. **JSON responses** — `{"con": ["[{...}]"], "totRecords": N, "Error": ""}`

### District Courts Portal

The District Courts portal (`services.ecourts.gov.in/ecourtindia_v6/`) uses a similar PHP backend with key differences:

1. **Session cookies** — `SERVICES_SESSID` (established on page load)
2. **Rotating `app_token`** — every AJAX response returns a new token that must be sent with the next request
3. **MVC-style AJAX** — `/?p=controller/action` URL pattern (e.g., `/?p=casestatus/submitCaseNo`)
4. **HTML responses** — search results are pre-rendered HTML tables (not JSON)
5. **4-level court hierarchy** — State → District → Court Complex → Establishment (discovered dynamically)

Both portals are handled transparently — session management, token rotation, CAPTCHA solving with retry, request/response parsing, and rate limiting.

### Historical Archive (AWS Open Data)

Two public S3 buckets in `ap-south-1`, CC-BY-4.0, maintained by Dattam Labs:

- `s3://indian-supreme-court-judgments/` — SCI judgments 1950–present, bi-monthly updates
- `s3://indian-high-court-judgments/` — 25 High Courts, quarterly updates

Both partition metadata as Hive-style parquet (SCI: `year=YYYY/`; HC:
`year=YYYY/court=<archive_id>_<state_code>/bench=<slug>/`) and ship PDFs in
per-year tar bundles. The HC bucket additionally exposes individual PDFs at
`data/pdf/year=…/court=…/bench=…/<basename>`, so single-PDF fetches don't
need to download the whole tar.

`ArchiveClient` reads anonymously via DuckDB's `httpfs` extension (no AWS
account needed), translates rows through `row_to_judgment()` into the unified
`Judgment` shape, and serves PDFs with on-disk LRU caching. CNR-only queries
auto-route via the 4-letter prefix — `DLHC*` → Delhi, `ESCR*` → SCI,
`HCBM*` → Bombay, `WBCH*` → Calcutta, etc. (the full mapping is in
`courts._CNR_PREFIX_TO_COURT_CODE`, verified against a 2020 sample of every
HC partition).

The archive is **complementary** to the live clients, not a replacement: it
only contains delivered judgments and lags by 2–3 months, so case status,
cause lists, and in-progress orders still need `HCServicesClient` /
`DistrictCourtClient`.

## License

[MIT](LICENSE)
