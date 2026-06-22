# Supreme Court (`SCIClient`)

`SCIClient` is the live client for the Supreme Court of India. It talks to the
official portal at [www.sci.gov.in](https://www.sci.gov.in) and does two things
reliably today:

1. **`list_recent_judgments()`** — scrapes the homepage "Latest Judgements /
   Orders" feed (the 50 most recent items), no CAPTCHA.
2. **`download_pdf()`** — fetches the PDF bytes for one of those judgments.

That is the whole live surface. Read the scope note below before you build on it.

## Scope: what this client does and does not do

!!! warning "Live SCI search is limited to the recent feed"
    The legacy `main.sci.gov.in` host that used to serve year/party search has
    been in long-term maintenance for years (every endpoint returns HTTP 503).
    The current `www.sci.gov.in` site only exposes older judgments and
    case-number search behind a CAPTCHA-protected form, and **that flow is not
    wired up yet** in this SDK.

    Concretely:

    - `search_by_year(year, month=None)` raises `NotImplementedError`.
    - `search_by_party(party_name)` raises `NotImplementedError`.

    For anything beyond "the most recent ~50 SC judgments", use the
    [historical archive](archive.md) (SCI 1950 to present) or the
    [`Judgments` facade](facade.md).

If you only need recent Supreme Court items — for a digest, a watch list, or a
"what landed this week" check — `list_recent_judgments()` is exactly the right
tool, and it needs no CAPTCHA and no credentials.

## Quick example

```python
import asyncio
from bharat_courts.sci import SCIClient


async def main():
    async with SCIClient() as client:
        recent = await client.list_recent_judgments(limit=10)
        for j in recent:
            print(f"{j.judgment_date}  {j.case_number}  {j.title}")

        # Download the PDF for the first item.
        if recent:
            j = await client.download_pdf(recent[0])
            with open("sci_latest.pdf", "wb") as f:
                f.write(j.pdf_bytes)

asyncio.run(main())
```

`SCIClient` is an async context manager; `async with` opens and closes the
underlying HTTP session for you.

## Methods

| Method | CAPTCHA | Returns | Description |
|--------|---------|---------|-------------|
| `list_recent_judgments(*, limit=50)` | No | `list[JudgmentResult]` | The homepage "Latest Judgements / Orders" feed. The portal caps this at 50; pass a smaller `limit` to truncate. |
| `download_pdf(judgment)` | No | `JudgmentResult` | Downloads the PDF bytes for a judgment. Mutates the object in place: sets `pdf_bytes` on success. |
| `search_by_year(year, month=None)` | — | — | **Not implemented** — raises `NotImplementedError`. Use the [archive](archive.md). |
| `search_by_party(party_name)` | — | — | **Not implemented** — raises `NotImplementedError`. Use the [archive](archive.md). |

### `list_recent_judgments(*, limit=50)`

Scrapes the homepage feed of the 50 most recent items. `limit` is keyword-only
and capped at 50 by the portal; passing a smaller value truncates the list
locally. Returns a list of `JudgmentResult` objects.

### `download_pdf(judgment)`

Takes a `JudgmentResult` (typically one returned by `list_recent_judgments()`)
and downloads its PDF. The judgment's `pdf_url` is the portal's
`/sci-get-pdf/?diary_no=...` link that the in-page viewer iframe uses.

- On success, the PDF bytes are stored on `judgment.pdf_bytes` and the same
  object is returned.
- If the judgment has no `pdf_url`, it raises `RuntimeError`.
- If the response is not a valid PDF (it does not start with the `%PDF` magic
  bytes), it raises `RuntimeError`.

## What you get back: `JudgmentResult`

Each item is a `JudgmentResult`. The fields most useful for the SCI feed:

| Field | Meaning |
|-------|---------|
| `title` | Case title (e.g. petitioner vs. respondent) |
| `case_number` | Case / diary number as shown on the portal |
| `judgment_date` | Date of the judgment or order |
| `judges` | Bench / authoring judges where available |
| `pdf_url` | The `/sci-get-pdf/?diary_no=...` download link |
| `pdf_bytes` | Populated by `download_pdf()` |
| `source_url` | The portal page the item was scraped from |

See the [models reference](../reference/models.md) for the full field list.

## SCI live feed vs. the historical archive

!!! info "Two different SCI sources — pick by recency"
    There are **two** ways to get Supreme Court judgments in bharat-courts, and
    they cover different windows:

    - **`SCIClient` (this page)** — live scrape of the portal homepage. Only the
      ~50 most recent items, but it is current to the minute and needs no
      CAPTCHA. Use it for "the latest SC judgments".
    - **[Historical archive](archive.md) (`ArchiveClient`)** — DuckDB queries
      over the AWS Open Data bucket of SCI judgments from **1950 to present**,
      with structured search by judge, year, party, citation, and CNR, plus
      regional-language PDFs. No CAPTCHA, no rate limits. It lags the live
      portal by roughly 2 months (bi-monthly updates), so the most recent
      handful of judgments may not be there yet.

    Rule of thumb: **last few weeks → `SCIClient`; everything older or any
    structured/bulk search → the archive.**

## When to reach for something else

- **Structured SC search** ("all Justice Chandrachud judgments 2018–2024",
  "judgments citing X") — use the [`Judgments` facade](facade.md), which routes
  these to the archive automatically:

    ```python
    import asyncio
    from bharat_courts import Judgments


    async def main():
        async with Judgments() as j:
            results = await j.find(
                court="sci", judge="chandrachud", year=(2018, 2024), limit=10,
            )
            for r in results:
                print(f"{r.decision_date}  {r.case_id}  {r.title}")

    asyncio.run(main())
    ```

- **A specific SC judgment by CNR** — `Judgments().find(cnr=...)` routes the CNR
  prefix straight to the archive partition. SCI CNRs start with the `ESCR`
  prefix.

- **Full-text search across SC reports** — the
  [judgment search portal](judgment-search.md) (`JudgmentSearchClient`) supports
  keyword search with `court_type="3"` (Supreme Court Reports).

## See also

- [Historical archive guide](archive.md) — SCI 1950 to present, structured and bulk search.
- [The `Judgments` facade](facade.md) — the recommended default entry point for finding any judgment.
- [Judgment search portal](judgment-search.md) — keyword full-text search.
- [Clients API reference](../reference/clients.md) — full signatures for `SCIClient` and the other live clients.
