# The Judgments facade

`Judgments` is the federated entry point for judgment search. Most callers want
*a judgment matching some criteria* and don't care whether it comes from the live
eCourts portal or the AWS Open Data archive. `Judgments` exposes one method —
`find(...)` — that takes any combination of filters, routes to the right backend,
and returns a uniform `list[Judgment]`.

This guide is the deep reference for that facade. For the backends it sits on top
of, see the [archive guide](archive.md) and the
[judgment-search guide](judgment-search.md); for the generated API surface see the
[facade API reference](../reference/facade.md).

## Why one entry point

There are two judgment backends with very different shapes:

- **Live** (`JudgmentSearchClient`) — the only backend that does full-body text
  search. CAPTCHA-gated, rate-limited.
- **Archive** (`ArchiveClient`) — DuckDB over the public S3 buckets. No CAPTCHA, no
  rate limits, partition-pruned, but lags 2–3 months and can only match text against
  titles.

Choosing between them by hand means reasoning about CAPTCHAs, partition pruning, and
freshness on every call. `Judgments.find()` makes that decision for you from the
shape of the query, logs which way it went, and hands back `Judgment` objects that
each carry a `.source` field (`"archive"` or `"live"`) so you always know the origin.

```python
import asyncio
from bharat_courts import Judgments

async def main():
    async with Judgments() as j:
        hits = await j.find(judge="chandrachud", year=2020, court="sci", limit=10)
        for r in hits:
            print(r.decision_date, r.case_id, r.title, f"[{r.source}]")

asyncio.run(main())
```

## Routing decision table (auto mode)

With the default `source="auto"`, `find()` inspects three things — whether `cnr` is
set, whether `text` is set, and whether any *structured* filter
(`court`, `year`, `judge`, `party`, `citation`) is set — and resolves a backend:

| `cnr` | `text` | structured | → backend | Why |
|---|---|---|---|---|
| set | any | any | **archive** | CNR prefix → court → partition; instant lookup |
| — | set | no | **live** | Only the live portal does full-body text search |
| — | — | yes | **archive** | Partition-pruned, no CAPTCHA |
| — | set | yes | **archive** | `text` folds into a title-substring match |
| — | — | — | `ValueError` | Need at least one filter |

The precedence is exactly that order: a `cnr` always wins, then text-only goes live,
then anything structured goes to the archive. Each decision is logged at INFO under
the `bharat_courts.facade` logger (`Judgments.find routing → archive`), so routing is
debuggable in production.

!!! warning "Mixed `text` + structured does a title match, not full-text"
    When you pass `text` *together with* a structured filter, `find()` routes to the
    **archive**, not live. The archive cannot do full-body search, so `text` is folded
    into the `party` slot, which matches against the title (and, for SCI, party
    columns). A query like `find(text="tata", court="delhi", year=2020)` therefore
    returns judgments whose *title* contains "tata" — not every Delhi 2020 judgment
    that *mentions* Tata in the body. This is intentional (it avoids silently burning
    a CAPTCHA and 30 seconds on a live call), but it is a real limitation: if you need
    true full-body search, pass `source="live"` with `text` alone.

### Forcing a backend

Set `source="archive"` or `source="live"` to bypass auto-routing entirely. The forced
value short-circuits before any of the auto rules are consulted.

```python
# Force live (e.g. for a case decided last month, before the archive catches up)
recent = await j.find(text="anticipatory bail", source="live", limit=5)

# Force archive even though you only passed text (title match only)
hist = await j.find(text="kesavananda", source="archive", limit=20)
```

!!! note "`source` is per-call, not a constructor setting"
    There is no `default_source` on `Judgments()`. Each override is explicit at the
    call site, so it's always obvious from the code which backend a given query used.

## `find()` signature

```python
async def find(
    self,
    *,
    text: str | None = None,
    court: Court | str | None = None,
    year: int | tuple[int, int] | None = None,
    judge: str | None = None,
    party: str | None = None,
    citation: str | None = None,
    cnr: str | None = None,
    source: Source = "auto",      # Literal["auto", "archive", "live"]
    limit: int = 50,
) -> list[Judgment]:
```

All parameters are keyword-only.

| Parameter | Type | Meaning |
|---|---|---|
| `text` | `str` | Free-text query. Alone → live full-text search. With a structured filter → archive title match. |
| `court` | `Court \| str` | A `Court` object or a registry code (`"delhi"`, `"sci"`, …). Structured filter. |
| `year` | `int \| tuple[int, int]` | A single year, or an inclusive `(start, end)` range. Structured filter. |
| `judge` | `str` | Judge-name substring. Structured filter. |
| `party` | `str` | Party-name substring (title + party columns on the archive). Structured filter. |
| `citation` | `str` | Citation substring. Structured filter. |
| `cnr` | `str` | Case Number Record id. Routes straight to the archive via its 4-letter prefix. |
| `source` | `"auto" \| "archive" \| "live"` | Routing override. Default `"auto"`. |
| `limit` | `int` | Max rows. Default `50`. For the live route, page size is capped at 25 internally and trimmed to `limit`. |

!!! info "Archive caveats inherited by structured queries"
    Structured queries land on `ArchiveClient.search`, so its limits apply: HC parquet
    has no separate party/citation columns, so on High Courts `party=` matches the
    title only and `citation=` is silently ignored. SCI behaves as documented. See the
    [archive guide](archive.md) for the full list.

## Worked examples, one per route

### CNR → archive

A CNR alone routes to the archive; the 4-letter prefix resolves the court and
partition, so the lookup is effectively instant and no other filter is needed.

```python
async with Judgments() as j:
    hits = await j.find(cnr="DLHC010230802020")
    if hits:
        print(hits[0].title, hits[0].decision_date)
```

### Text only → live

Free text with no structured filter is the one case that goes to the live portal,
because it is the only backend that searches the full body of a judgment.

```python
async with Judgments() as j:
    for r in await j.find(text="right to privacy", limit=5):
        print(r.decision_date, r.title, f"[{r.source}]")  # source == "live"
```

### Structured only → archive

Any structured filter — judge, party, year, court, or citation — with no `text` goes
to the archive: partition-pruned, no CAPTCHA, fast.

```python
async with Judgments() as j:
    hits = await j.find(judge="chandrachud", year=(2018, 2024), court="sci", limit=10)
    for r in hits:
        print(r.decision_date, r.citation, r.disposal_nature)
```

### Text + structured → archive (title match)

Combining `text` with a structured filter stays on the archive and folds `text` into a
title match. See the warning above for the limitation.

```python
async with Judgments() as j:
    # Delhi HC judgments from 2020 whose TITLE contains "tata"
    hits = await j.find(text="tata", court="delhi", year=2020)
```

### Nothing → `ValueError`

```python
await j.find()  # raises ValueError: needs at least one of text, cnr, or a
                # structured filter (court / year / judge / party / citation)
```

## `fetch_pdf()`

```python
async def fetch_pdf(
    self,
    judgment_or_cnr: Judgment | str,
    *,
    language: str = "english",
) -> bytes:
```

Pass either a `Judgment` (from the archive route) or a CNR string. The facade routes
both to `ArchiveClient.fetch_pdf`, which returns the raw PDF bytes. SCI supports
regional languages via `language=` (`"hindi"`, `"tamil"`, `"gujarati"`, …); HC PDFs
are English only.

```python
async with Judgments() as j:
    hits = await j.find(cnr="DLHC010230802020")
    pdf = await j.fetch_pdf(hits[0])              # or: await j.fetch_pdf("DLHC010230802020")
    with open("judgment.pdf", "wb") as f:
        f.write(pdf)
```

!!! warning "Live `Judgment` objects cannot be fetched through the facade"
    If you pass a `Judgment` whose `.source == "live"`, `fetch_pdf()` raises
    `NotImplementedError`. The live download path needs the *original*
    `JudgmentResult` instance — it carries CAPTCHA-validated session state that a bare
    `Judgment` does not. The documented workaround is to call the live client directly:

    ```python
    from bharat_courts import JudgmentSearchClient

    async with JudgmentSearchClient() as client:
        result = await client.search("right to privacy")
        jr = result.items[0]                      # a JudgmentResult, session-bound
        jr = await client.download_pdf(jr)        # fills jr.pdf_bytes in place
        with open("judgment.pdf", "wb") as f:
            f.write(jr.pdf_bytes)
    ```

    Do not try to round-trip a live PDF through `Judgments` — the session continuity
    the live portal needs lives on the `JudgmentResult`, not on the unified `Judgment`.

## `live_to_judgment()` helper

When you call the live client directly but want the unified `Judgment` shape (for
example, to mix live and archive results in one list), use the module-level helper
`live_to_judgment(jr: JudgmentResult) -> Judgment`. This is exactly what `find()` uses
internally on the live route.

```python
from bharat_courts import JudgmentSearchClient
from bharat_courts.facade import live_to_judgment

async with JudgmentSearchClient() as client:
    result = await client.search("constitution")
    unified = [live_to_judgment(jr) for jr in result.items]  # list[Judgment]
```

Field mapping:

| `JudgmentResult` | `Judgment` |
|---|---|
| `title` | `title` |
| `court_name` | `court_name_raw`; also resolved into `court` via the courts registry when a match is found |
| `source_id` | `cnr` (the judgments portal uses CNR as its row id) |
| `judges` | `judges` |
| `judgment_date` | `decision_date` (and its `.year` → `year`) |
| `citation` | `citation` (when non-empty) |
| `pdf_url` | `pdf_path` (raw path only — live download still needs the original `JudgmentResult`) |
| `metadata["disposal_nature"]` | `disposal_nature` |
| `metadata["registration_date"]` | `date_of_registration` (parsed from `YYYY-MM-DD`) |

The resulting `Judgment` always has `source="live"`, which is what later makes
`fetch_pdf()` reject it (see the warning above).

## Lazy backends and extras

`Judgments()` owns both an `ArchiveClient` and a `JudgmentSearchClient`, but neither is
created until a query actually routes to it. This means you only pay for — and only
need to install — the side you use:

```bash
pip install 'bharat-courts[archive]'   # archive backend (DuckDB)
pip install 'bharat-courts[ocr]'       # live backend (ddddocr CAPTCHA solving)
pip install 'bharat-courts[all]'       # everything
```

For the full federated experience, install **both** `[archive]` and `[ocr]` so
`find()` can use either backend. If a query routes to the archive but the `[archive]`
extra isn't installed, the facade raises a clear `ImportError` telling you exactly
which extra to install.

!!! tip "Always use the async context manager"
    Open the facade with `async with Judgments() as j:`. On exit it closes whichever
    backends were lazily created — `ArchiveClient.close()` for the archive, and a clean
    `__aexit__` on the live client (which it keeps alive across `find()` calls so a
    session and CAPTCHA aren't re-established every time). If you can't use a `with`
    block, call `await j.aclose()` yourself when done.

## See also

- [Historical archive guide](archive.md) — the backend behind every structured and CNR query.
- [Judgment search guide](judgment-search.md) — the live full-text backend and direct PDF download.
- [Facade API reference](../reference/facade.md) — generated signatures for `Judgments`, `Source`, and `live_to_judgment`.
