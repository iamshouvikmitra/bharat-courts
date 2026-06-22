# Quickstart

The fastest path to a result is the federated `Judgments` facade. You describe the
judgment you want — by judge, year, court, free text, or CNR — and the SDK picks the
right backend (the historical AWS archive or the live eCourts portal), runs the query,
and hands back a uniform list of `Judgment` objects.

If you have not installed the library yet, see [Installation](installation.md). For the
facade to use both backends, install both extras:

```bash
pip install 'bharat-courts[archive,ocr]'
```

!!! tip "Lawyers: you may not need any code at all"
    If you are a practising lawyer, the easiest way to use bharat-courts is through your
    AI assistant. Install the bundled skill once and then ask questions in plain English —
    no Python required. See the [guide for lawyers](../lawyers/index.md).

## One entry point: `Judgments`

```python
import asyncio
from bharat_courts import Judgments

async def main():
    async with Judgments() as j:
        # 1. Structured filters → archive (no CAPTCHA, partition-pruned)
        results = await j.find(judge="chandrachud", year=(2018, 2024), court="sci", limit=10)
        for r in results:
            print(f"{r.decision_date}  {r.case_id}  {r.title}  [{r.source}]")

        # 2. Free text → live (only the live portal does full-body search)
        for r in await j.find(text="right to privacy", limit=5):
            print(f"{r.decision_date}  {r.title}  [{r.source}]")

        # 3. CNR alone → archive (the 4-letter prefix routes to the right bucket)
        hits = await j.find(cnr="DLHC010230802020")
        if hits:
            pdf_bytes = await j.fetch_pdf(hits[0])
            with open("judgment.pdf", "wb") as f:
                f.write(pdf_bytes)

asyncio.run(main())
```

Three things to notice:

- **`find()` is the only call you make.** You never decide between archive and live —
  the facade reads the shape of your query and routes for you.
- **Every result is a `Judgment`** with the same fields regardless of where it came from
  (`decision_date`, `title`, `case_id`, `citation`, `judges`, `disposal_nature`, and more).
- **`r.source`** is `"archive"` or `"live"` on each item, so you can always tell which
  backend answered.

!!! info "PDFs for live results"
    `fetch_pdf()` works for archive judgments and for CNR strings whose prefix maps to a
    known court. It raises `NotImplementedError` for a live `Judgment` (the live download
    needs the original session-bound search result). For those, call
    `JudgmentSearchClient.download_pdf(...)` directly — see
    [Judgment search](../guides/judgment-search.md).

## How `find()` routes

In the default `source="auto"` mode, the facade picks a backend from the filters you pass:

| What you pass | Backend | Why |
|---|---|---|
| `cnr=` set | archive | The 4-letter CNR prefix resolves to a court and partition — no scan |
| `text=` only | live | Only the live judgments portal does full-body text search |
| structured only (`judge`, `party`, `year`, `court`, `citation`) | archive | Partition-pruned, no CAPTCHA, no rate limits |
| `text=` + structured | archive | `text` folds into a title-substring match (the `party` slot) |
| nothing | — | raises `ValueError` — give at least one filter |

You can override the choice with `source="archive"` or `source="live"`:

```python
# Force the live portal — e.g. for a case decided in the last few weeks
recent = await j.find(text="bail", source="live", limit=5)
```

!!! note "Freshness gap"
    The archive lags the courts by a few months (SCI updates bi-monthly, High Courts
    quarterly). If a structured query returns nothing for a very recent year, retry with
    `source="live"` or use the live clients directly.

### `find()` parameters

| Parameter | Type | Description |
|---|---|---|
| `text` | `str \| None` | Free-text keyword search. Routes to live on its own. |
| `court` | `Court \| str \| None` | Court object or code (`"sci"`, `"delhi"`, …). |
| `year` | `int \| tuple[int, int] \| None` | Single year or inclusive range. Strongly recommended for non-CNR queries. |
| `judge` | `str \| None` | Substring on the judge field (archive). |
| `party` | `str \| None` | Substring on petitioner/respondent (SCI) or title (HC). |
| `citation` | `str \| None` | Citation substring (archive, SCI only). |
| `cnr` | `str \| None` | Exact CNR. Auto-routes via the prefix in `auto` mode. |
| `source` | `"auto" \| "archive" \| "live"` | Override automatic routing. Default `"auto"`. |
| `limit` | `int` | Total results to return. Default `50`. |

The routing decision is logged at INFO under `logging.getLogger("bharat_courts.facade")`,
so it is easy to confirm what happened in production.

## The same thing from the command line

The CLI mirrors `find()`. The `--json` flag is global, so it goes **before** the
subcommand. Install the CLI with `pip install 'bharat-courts[cli]'` (or `[all]`).

```bash
# Structured: judge + year range + court
bharat-courts find --judge chandrachud --year 2018-2024 --court sci --limit 10

# Free text (routes to live)
bharat-courts find --text "right to privacy" --limit 5

# CNR (routes to archive via the prefix)
bharat-courts find --cnr DLHC010230802020

# Force a backend
bharat-courts find --text bail --source live --limit 5

# Machine-readable output — note --json comes before `find`
bharat-courts --json find --cnr DLHC010230802020
```

`--year` accepts a single year (`2020`) or a hyphenated range (`2018-2024`). The default
`--limit` for the CLI is `20`. The full command reference is in the
[CLI guide](../guides/cli.md).

## Next steps

<div class="grid cards" markdown>

-   :material-source-branch: __The facade in depth__

    Routing internals, forcing a backend, and combining text with structured filters.

    [:octicons-arrow-right-24: Federated facade](../guides/facade.md)

-   :material-bank: __High Courts__

    Case status, orders, and cause lists across 25+ High Courts via `HCServicesClient`.

    [:octicons-arrow-right-24: High Courts](../guides/high-courts.md)

-   :material-database-search: __Historical archive__

    Bulk streaming, PDF retrieval, and the AWS Open Data buckets (1950–present).

    [:octicons-arrow-right-24: Archive](../guides/archive.md)

-   :material-console: __Command line__

    Every subcommand, global flags, and JSON output for scripting.

    [:octicons-arrow-right-24: CLI](../guides/cli.md)

</div>
