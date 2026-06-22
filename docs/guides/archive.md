# Historical Archive (`ArchiveClient`)

`ArchiveClient` reads two **public AWS Open Data** S3 buckets directly with
DuckDB. It is the engine behind every historical and bulk query in
bharat-courts: no CAPTCHA, no rate limits, and no AWS account required.

Reach for the archive when the user wants **historical research**, **bulk PDF
retrieval**, or a judgment with a **known CNR**. For *current* state — case
status, next hearing, cause lists, orders just uploaded — use the live clients
instead (see [High Courts](high-courts.md) and
[Judgment Search](judgment-search.md)).

!!! info "Where this sits"
    Most callers should start with the [`Judgments` facade](facade.md), which
    calls `ArchiveClient` for you and routes archive-vs-live by query shape.
    Drop down to `ArchiveClient` directly only for archive-specific operations
    the facade does not expose — chiefly `iter_judgments` (bulk streaming) and
    `prefetch_sci_year` (pre-warming the cache).

## The data

| Bucket | Coverage | Update cadence |
|---|---|---|
| `s3://indian-supreme-court-judgments/` | Supreme Court of India, **1950 → present** | bi-monthly |
| `s3://indian-high-court-judgments/` | **25 High Courts** | quarterly |

Both buckets live in `ap-south-1`, are licensed **CC-BY-4.0**, and are
maintained by **Dattam Labs**. Because the data is public, anonymous S3 access
is used — you do not need credentials.

See [Data sources](../about/data-sources.md) for the full provenance and
attribution details.

## Installation

The archive is an opt-in extra (it pulls in DuckDB):

```bash
pip install "bharat-courts[archive]"
```

## Quick start

```python
import asyncio
from bharat_courts import ArchiveClient

async def main():
    async with ArchiveClient() as client:
        # Search by judge + year range (partition-pruned in DuckDB)
        results = await client.search(
            court="sci", judge="chandrachud", year=(2018, 2024), limit=20,
        )
        for j in results:
            print(f"{j.decision_date}  {j.case_id}  {j.title}")
            print(f"  {j.citation}  outcome: {j.disposal_nature}")

asyncio.run(main())
```

Every row comes back as a unified [`Judgment`](../reference/models.md) with
`.source = "archive"`, so it interoperates with results from the live clients
and the facade.

## Method reference

| Method | Returns | Description |
|---|---|---|
| `search(*, court=None, year=None, judge=None, party=None, citation=None, cnr=None, limit=50)` | `list[Judgment]` | One-shot search across both buckets (or just one if `court` is given). CNR-only queries auto-route via the prefix. |
| `iter_judgments(*, court=None, year=None, judge=None, party=None, citation=None, cnr=None, batch_size=500, max_results=None)` | `AsyncIterator[Judgment]` | Stream pages via `LIMIT`/`OFFSET` with a stable sort. Use for more than ~50 rows. |
| `fetch_pdf(judgment_or_cnr, *, language="english")` | `bytes` | PDF bytes. Pass a `Judgment` to skip the lookup, or a CNR string. SCI supports regional languages. |
| `prefetch_sci_year(year, language="english")` | `str` (local path) | Pre-warm a SCI year tar before a batch of fetches. |
| `count(*, court=None, year=None)` | `dict[str, int]` | Per-bucket row counts. |
| `cache_info()` | `dict` | `cache_dir`, `files`, `bytes`, `max_bytes`. |

### Shared filter arguments

`search`, `iter_judgments`, and `count` share the same filter vocabulary:

| Argument | Type | Notes |
|---|---|---|
| `court` | `Court \| str \| None` | A `Court`, a code (`"sci"`, `"delhi"`), or `None` to query **both** SCI and all 25 HCs. |
| `year` | `int \| tuple[int, int] \| None` | Single year (`2020`) or inclusive range (`(2018, 2024)`). Strongly recommended — drives partition pruning. (`count` takes a single `int` only.) |
| `judge` | `str` | Case-insensitive substring match. |
| `party` | `str` | SCI: matches petitioner, respondent, and title. HC: title only (see warning below). |
| `citation` | `str` | SCI only — silently ignored for HC. |
| `cnr` | `str` | Exact match. When `court` is omitted, the 4-letter prefix infers the court automatically. |

## Worked examples

### Judge + year-range search

```python
async with ArchiveClient() as client:
    results = await client.search(
        court="delhi", judge="hari shankar", year=(2019, 2021), limit=25,
    )
    for j in results:
        print(j.decision_date, j.case_id, j.title)
```

### CNR lookup (court auto-inferred)

You do not need to pass `court` when you have a CNR — the first four letters of
the CNR identify the bucket and partition, so the lookup is instant and avoids
scanning all 25 HC partitions.

```python
async with ArchiveClient() as client:
    results = await client.search(cnr="DLHC010230802020")   # → Delhi HC
    sci = await client.search(cnr="ESCR010000301950")       # → Supreme Court
```

!!! tip "Inspect the routing yourself"
    `bharat_courts.infer_court_from_cnr(cnr)` returns the resolved `Court`
    (or `None`, never raising) so you can see exactly where a CNR will route.
    Note the legacy prefixes: Bombay = `HCBM`, Madras = `HCMA`,
    Telangana = `HBHC`, Calcutta = `WBCH`.

### Bulk streaming with `iter_judgments`

For large pulls — "every Delhi 2020 judgment" is roughly 18,000 rows — stream
instead of using a huge `limit`. Pages are fetched via `LIMIT`/`OFFSET`, so you
start consuming results immediately and never hold the full set in memory.

```python
async with ArchiveClient() as client:
    count = 0
    async for j in client.iter_judgments(court="delhi", year=2020, batch_size=500):
        count += 1
        # process(j) — write to a file, index, etc.
    print(f"Streamed {count} judgments")
```

Sources stream sequentially (SCI first, then HC) and each source is internally
sorted by `decision_date DESC, cnr`, so individual pages are deterministic.
There is **no** cross-source date merge across SCI and HC in streaming mode.
Use `max_results=N` to cap the total yielded across sources.

### Fetch a PDF to disk

`fetch_pdf` accepts either a `Judgment` (preferred — no extra lookup) or a CNR
string (which triggers one metadata query first).

```python
async with ArchiveClient() as client:
    pdf_bytes = await client.fetch_pdf("DLHC010230802020")
    with open("judgment.pdf", "wb") as f:
        f.write(pdf_bytes)
```

### Regional-language SCI PDF

The Supreme Court archive carries regional-language renderings. The `language`
argument is only meaningful for SCI — HC PDFs in the archive are English-only.

```python
async with ArchiveClient() as client:
    hindi = await client.fetch_pdf("ESCR010000301950", language="hindi")
    # other values: "tamil", "gujarati", … (see SCI_LANGUAGE_MAP)
```

### Pre-warm a year before a batch

If you are about to fetch many SCI PDFs from the same year, warm the tar once
so the per-PDF fetches are cheap:

```python
async with ArchiveClient() as client:
    local_tar = await client.prefetch_sci_year(2020)
    print("warmed:", local_tar)
    # subsequent fetch_pdf(...) calls for 2020 read from this tar
```

### Sizing a query with `count`

```python
async with ArchiveClient() as client:
    print(await client.count(court="delhi", year=2020))  # {"hc": 18000}
    print(await client.count(year=2020))                 # {"sci": ..., "hc": ...}
```

## Gotchas

!!! warning "Freshness lag"
    The archive is **not** real-time. SCI updates bi-monthly and HC updates
    quarterly, so anything decided in the last 2–3 months may not be present.
    If a structured query returns nothing for a recent year, fall back to the
    live `JudgmentSearchClient` / `HCServicesClient` (or call the facade with
    `source="live"`), and tell the user about the gap.

!!! warning "No party or citation search on High Courts"
    The HC parquet has no separate `petitioner`/`respondent` columns and no
    `citation` column. As a result `party=` matches against the **title only**
    for HC, and `citation=` is **silently ignored** for HC. SCI supports both
    as expected.

!!! warning "First SCI fetch downloads a large tar"
    SCI PDFs are packaged one tar per year (~40–500 MB). The first
    `fetch_pdf` for a given SCI year downloads that whole tar; subsequent
    fetches in the same year are essentially free (random-access from the
    cached tar). Warn the user before kicking off SCI fetches spanning many
    years. HC PDFs, by contrast, are fetched per-file (~250 KB each).

!!! note "On-disk PDF cache and the size cap"
    PDFs and tars cache under `~/.cache/bharat-courts/archive/` with a **5 GiB**
    default cap and LRU eviction. Override the cap with the
    `BHARAT_COURTS_ARCHIVE_CACHE_MAX_GB` environment variable. Inspect the cache
    at any time with `cache_info()`, which returns `cache_dir`, `files`,
    `bytes`, and `max_bytes`.

!!! note "Attribution (CC-BY-4.0)"
    When you redistribute archive data or PDFs, attribute **Dattam Labs /
    eCourts** per the CC-BY-4.0 licence.

## See also

- [API reference: `ArchiveClient`](../reference/archive.md) — full signatures and types.
- [The `Judgments` facade](facade.md) — the recommended default that routes between archive and live for you.
- [Data sources](../about/data-sources.md) — bucket provenance, licence, and update cadence.
