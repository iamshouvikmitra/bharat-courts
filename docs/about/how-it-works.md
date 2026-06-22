# How it works

bharat-courts gives you — and your AI assistant — programmatic access to Indian
court data that otherwise lives behind clunky portals and hand-typed CAPTCHAs.
Under the hood it is built from three pillars: a set of **live clients** that
scrape the official eCourts portals, an **archive client** that queries a public
historical dataset on AWS, and a **federated facade** that picks between them for
you and returns one uniform result type.

This page is a conceptual map of those pieces and how a query flows through them.
It is semi-technical — useful if you want to understand the trade-offs, debug a
result, or decide which entry point to reach for.

## The big picture

```text
        your AI agent  /  your Python code  /  the CLI
                              │
                              ▼
                  ┌───────────────────────┐
                  │   Judgments  (facade)  │   routes by query shape
                  └───────────┬───────────┘
                  ┌───────────┴───────────┐
                  ▼                       ▼
        ┌──────────────────┐    ┌──────────────────────┐
        │   Live clients   │    │   Archive client      │
        │  (scrape portals)│    │  (DuckDB over AWS S3)  │
        └────────┬─────────┘    └───────────┬──────────┘
                 ▼                          ▼
   hcservices / services /        s3://indian-supreme-court-judgments
   judgments / sci.gov.in /       s3://indian-high-court-judgments
   calcuttahighcourt.gov.in       (AWS Open Data, CC-BY-4.0)
        OFFICIAL eCOURTS               PUBLIC ARCHIVE MIRROR
```

Everything resolves to **official sources**: either the live eCourts/Supreme
Court portals, or the AWS Open Data buckets that mirror published judgments.
bharat-courts never invents data — it fetches, parses, and normalises what those
sources already publish.

## Pillar 1 — Live clients (the official portals)

The live clients scrape the same portals a lawyer would open in a browser. They
answer questions about the **current** state of a matter: today's case status,
the orders filed so far, tomorrow's cause list, the most recent Supreme Court
judgments.

| Client | Portal | Answers |
|---|---|---|
| `HCServicesClient` | hcservices.ecourts.gov.in | High Court case status, orders, cause lists |
| `DistrictCourtClient` | services.ecourts.gov.in | 700+ district court complexes |
| `JudgmentSearchClient` | judgments.ecourts.gov.in | Full-text judgment search + bulk PDF download |
| `SCIClient` | www.sci.gov.in | Recent Supreme Court judgments feed |
| `CalcuttaHCClient` | calcuttahighcourt.gov.in | Calcutta HC orders direct from the court website |

Characteristics of the live path:

- **CAPTCHA-gated.** Most search calls require solving an image CAPTCHA. The SDK
  handles this automatically with a pluggable solver (OCR, ONNX, or your own) and
  retries with a fresh session on failure. See the
  [CAPTCHA guide](../guides/captcha.md).
- **Rate-limited.** Requests go through a rate-limited HTTP client with retries
  and browser-like headers, so you stay polite to the portals.
- **Live and current.** This is the only way to see in-progress matters,
  pending-case lists, and judgments delivered in the last few months.

!!! note "Some live calls need no CAPTCHA"
    Discovery calls — listing benches, case types, districts, or court
    complexes — and the Supreme Court recent-judgments feed do not require a
    CAPTCHA. Only the actual case/judgment searches do.

### The HC Services portal protocol (high level)

The High Court portal is session-bound, and the CAPTCHA is pinned to that
session. At a high level, a search is a four-step dance the client performs for
you:

1. **Establish a session** — `GET main.php` sets the session cookie.
2. **Fetch the CAPTCHA** — `GET securimage_show.php` returns the image, pinned to
   that session.
3. **Search** — `POST` the case query with the solved CAPTCHA; the portal returns
   JSON.
4. **Parse** — the client strips the response envelope and maps rows into clean
   `CaseInfo` / `CaseOrder` objects.

Because the CAPTCHA is pinned to the session, each retry needs a *fresh* session
— which is exactly what the client does behind the scenes. You never write any of
this yourself; you call `case_status(...)` and get back parsed results.

## Pillar 2 — The archive client (AWS Open Data)

The archive client (`ArchiveClient`, installed via the `[archive]` extra) reads
two public AWS Open Data buckets maintained by Dattam Labs:

- `s3://indian-supreme-court-judgments/` — the Supreme Court, **1950 to present**
- `s3://indian-high-court-judgments/` — **25 High Courts**

Both are CC-BY-4.0 licensed. Instead of scraping HTML, the archive runs SQL
directly against partitioned **parquet** files using **DuckDB**, with anonymous
(no-account) S3 access. PDFs are then pulled by direct HTTP GET (one file per High
Court judgment) or random-access tar extraction (one tar per Supreme Court year).
Both the metadata shards and the PDFs cache on disk under
`~/.cache/bharat-courts/archive/`.

Characteristics of the archive path:

- **No CAPTCHA, no rate limits, no accounts.** It is plain object storage.
- **Fast and partition-pruned.** Supplying a `year` and `court` lets DuckDB skip
  straight to the relevant shards, so even large queries stay quick.
- **Historical, with a freshness gap.** The buckets refresh bi-monthly (Supreme
  Court) and quarterly (High Courts), so they lag real-world filings by roughly
  2–3 months. For anything decided in the last couple of months, use the live
  path instead.

This is the right backend for research workloads — "every judgment by Justice X",
"all 2020 Delhi writ petitions", bulk PDF retrieval. See the
[archive guide](../guides/archive.md) and the
[data sources page](data-sources.md) for the full picture.

## Pillar 3 — The `Judgments` facade (routing for you)

Most of the time you want *a judgment matching some criteria* and do not care
whether it came from a live portal or the archive. The `Judgments` facade is the
recommended default. It owns both backends — lazily, so you only pay for what you
install — exposes a single `find(...)` method, and returns a uniform
`list[Judgment]` regardless of source. Each returned `Judgment` carries a
`source` field (`"archive"` or `"live"`) so you can still tell where it came from.

### How it routes

The facade inspects the *shape* of your query and picks a backend. With the
default `source="auto"`:

| Filter shape | Backend chosen | Why |
|---|---|---|
| `cnr=` set | archive | the CNR prefix resolves directly to a court partition — no scan |
| `text=` only | live | only the live judgments portal does full-body text search |
| structured only (`court`/`year`/`judge`/`party`/`citation`) | archive | faster, no CAPTCHA |
| `text=` + structured | archive | `text` folds into a title-substring match |
| nothing | — | raises `ValueError` |

You can always override with `source="archive"` or `source="live"`.

Every routing decision is logged at INFO under the `bharat_courts.facade`
logger, so the choice is debuggable in production.

!!! info "Mixed text + structured stays on the archive"
    When you combine `text=` with structured filters, the facade routes to the
    archive and folds your `text` into a title/party substring match. The archive
    cannot do full-body search — but it is far faster than burning a CAPTCHA on
    the live portal, and the behaviour is predictable.

!!! warning "Live PDF fetch is not handled by the facade"
    `Judgments.fetch_pdf()` works for archive judgments and for CNR strings whose
    prefix maps to an archive-supported court. Passing a `Judgment` with
    `source="live"` raises `NotImplementedError`: the live download needs the
    original `JudgmentResult` (for the CAPTCHA-validated session). For those, call
    `JudgmentSearchClient.download_pdf(...)` directly.

A minimal end-to-end example:

```python
import asyncio
from bharat_courts import Judgments

async def main():
    async with Judgments() as j:
        # Structured → archive (no CAPTCHA, partition-pruned)
        for r in await j.find(judge="chandrachud", year=(2018, 2024),
                              court="sci", limit=10):
            print(r.decision_date, r.case_id, r.title, f"[{r.source}]")

        # Free-text → live (only it does full-body search)
        for r in await j.find(text="right to privacy", limit=5):
            print(r.title, f"[{r.source}]")

        # CNR alone → archive, prefix-routed, no scan
        result = await j.find(cnr="DLHC010230802020")
        pdf = await j.fetch_pdf(result[0])

asyncio.run(main())
```

See the [facade guide](../guides/facade.md) for the full method reference.

## CNR-prefix routing

Every Indian case has a 16-character **CNR** (Case Number Record) number, and its
first four letters identify the court. bharat-courts uses this to route a CNR
straight to the correct source without scanning every bucket.

The helper is `infer_court_from_cnr(cnr)`:

```python
from bharat_courts import infer_court_from_cnr

infer_court_from_cnr("DLHC010230802020")  # → Delhi High Court
infer_court_from_cnr("ESCR010000301950")  # → Supreme Court of India
infer_court_from_cnr("ZZZZ012345")        # → None
```

It is verified against all 25 High Court partitions plus the Supreme Court. Both
`ArchiveClient.search(cnr=...)` and the `Judgments` facade apply it automatically
for CNR-only queries — so a `fetch_pdf("DLHC...")` knows it needs the High Court
bucket without you naming the court.

??? note "A few prefixes are not the obvious abbreviation"
    Most CNR prefixes follow a `<state>HC…` pattern, but a handful do not —
    Bombay uses `HCBM`, Madras `HCMA`, Telangana `HBHC`, and Calcutta `WBCH`.
    The full mapping is baked into the court registry, so you never have to
    memorise these.

## Where the data comes from

To keep the chain of trust clear:

- **Live results** are scraped from the official eCourts and Supreme Court
  portals at the moment you ask. They reflect the current state of the matter.
- **Archive results** come from the AWS Open Data buckets — a published mirror of
  decided judgments, refreshed periodically and licensed CC-BY-4.0.

Neither path adds editorial content. For more on the buckets, update cadence, and
attribution requirements, see [Data sources](data-sources.md).
