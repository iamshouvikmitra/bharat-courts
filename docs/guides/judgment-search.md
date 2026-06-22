# Judgment Search Portal

`JudgmentSearchClient` is the live client for **judgments.ecourts.gov.in** — the
official eCourts portal that does **full-text keyword search** over High Court (and
Supreme Court Reports) judgments. Give it a phrase or set of words and it returns
matching judgments, each with a downloadable PDF.

This is the only backend in bharat-courts that searches the *body* of a judgment.
The historical archive can match on title and structured fields, but not on the
words inside the text — so when a user says "find me judgments that *mention* X",
this is the portal that can answer it.

!!! note "Keyword search only — no party / CNR / case-number search here"
    This portal supports **keyword / full-text search only**. There is no search by
    party name, CNR, or case number on judgments.ecourts.gov.in. For those, use
    `HCServicesClient` (High Courts) or `DistrictCourtClient` (district courts), or
    look the judgment up in the archive by CNR. See
    [High Courts](high-courts.md) and [District Courts](district-courts.md).

!!! tip "Most callers should use the `Judgments` facade instead"
    For the everyday "find a judgment matching X" question, prefer the federated
    [`Judgments` facade](facade.md). It routes free-text queries to this portal for
    you, folds in structured filters, and returns a uniform `Judgment` list — without
    you having to reason about which backend to call. Reach for `JudgmentSearchClient`
    directly when you specifically want portal-level control (page size, court type,
    batch PDF downloads).

## How it works

The portal is CAPTCHA-gated. The client handles the whole dance for you:

1. Establishes a session.
2. Fetches the CAPTCHA image and solves it with the configured solver.
3. Validates the CAPTCHA, receiving an `app_token` that must be echoed on every
   subsequent request.
4. Runs the search (a DataTables AJAX call) and parses the result rows.
5. For each downloaded PDF, exchanges the row's path for a per-session download URL,
   then fetches the bytes.

The session token rotates on every call and the client tracks it automatically. If
the session expires mid-pagination, `search_all()` re-authenticates and continues.

!!! info "CAPTCHA solver required"
    Like the other live clients, this one needs a CAPTCHA solver. With
    `bharat-courts[ocr]` installed the default `OCRCaptchaSolver` (ddddocr) is used
    automatically — no explicit solver argument needed. See [CAPTCHA handling](captcha.md).

## Method reference

| Method | CAPTCHA | Returns | Description |
|---|---|---|---|
| `search(search_text, *, page=1, page_size=10, search_opt="PHRASE", court_type="2", max_captcha_attempts=5)` | Yes | `SearchResult` | Search judgments by keyword (one page). |
| `search_all(search_text, *, page_size=25, search_opt="PHRASE", court_type="2", max_captcha_attempts=5)` | Yes | `AsyncIterator[SearchResult]` | Paginate through every page; re-authenticates if the session token expires mid-walk. |
| `download_pdf(judgment, *, court_type="2")` | No | `JudgmentResult` | Download the PDF for one result; sets `pdf_bytes` on the object in place. |
| `download_pdfs(judgments, *, court_type="2", stop_on_error=False)` | No | `list[JudgmentResult]` | Batch download; skips results that already have `pdf_bytes`, logs failures unless `stop_on_error=True`. |

### `search_opt` values

| Value | Meaning |
|---|---|
| `"PHRASE"` | Match the words as an exact phrase (the default). |
| `"ANY"` | Match judgments containing **any** of the words. |
| `"ALL"` | Match judgments containing **all** of the words (any order). |

### `court_type` values

| Value | Meaning |
|---|---|
| `"2"` | High Courts (the default). |
| `"3"` | Supreme Court Reports (SCR). |

### What you get back

`search()` and each page from `search_all()` return a `SearchResult`:

| Field | Description |
|---|---|
| `items` | List of `JudgmentResult` for this page. |
| `total_count` | Total matching judgments across all pages. |
| `page` / `page_size` | Current page and rows per page. |
| `has_next` / `total_pages` | Pagination helpers. |

Each `JudgmentResult` carries `title`, `court_name`, `case_number`, `judgment_date`,
`judges`, `citation`, `pdf_url`, `pdf_bytes`, `source_url`, `source_id`, and a
`metadata` dict. After `download_pdf()`, `pdf_bytes` holds the PDF.

## Single-page search

```python
import asyncio
from bharat_courts import JudgmentSearchClient

async def main():
    async with JudgmentSearchClient() as client:
        result = await client.search(
            "right to privacy",
            search_opt="ALL",   # match all of the words
            court_type="2",     # High Courts
            page_size=25,
        )
        print(f"{result.total_count} matches; showing {len(result.items)}")
        for j in result.items:
            print(f"{j.judgment_date}  {j.court_name}  {j.title}")

asyncio.run(main())
```

## Paginate through every result

`search_all()` is an async generator that yields one `SearchResult` per page and
stops when there are no more rows. It transparently re-authenticates if the portal
session expires during a long walk.

```python
import asyncio
from bharat_courts import JudgmentSearchClient

async def main():
    async with JudgmentSearchClient() as client:
        all_items = []
        async for page in client.search_all(
            "compassionate appointment",
            search_opt="PHRASE",
            page_size=50,
        ):
            print(f"page {page.page}/{page.total_pages}  (+{len(page.items)})")
            all_items.extend(page.items)
        print(f"collected {len(all_items)} judgments")

asyncio.run(main())
```

!!! warning "Pagination burns CAPTCHA solves and hits a rate-limited portal"
    Each search authenticates against a CAPTCHA, and the portal is rate-limited
    (the client paces requests for you). Walking thousands of results can be slow
    and may exhaust CAPTCHA retries. For large historical pulls, the
    [archive](archive.md) (`ArchiveClient.iter_judgments`) is faster and imposes no
    portal load — but note it can only match on title / structured fields, not on the
    judgment body.

## Download PDFs

`download_pdf()` mutates the `JudgmentResult` in place, setting `pdf_bytes`. The
row's `pdf_url` is a portal-internal path, not a directly fetchable URL — the client
resolves it through the portal's download endpoint for you.

```python
import asyncio
from bharat_courts import JudgmentSearchClient

async def main():
    async with JudgmentSearchClient() as client:
        result = await client.search("medical negligence", search_opt="PHRASE")

        # One PDF
        first = await client.download_pdf(result.items[0])
        with open("judgment.pdf", "wb") as f:
            f.write(first.pdf_bytes)

asyncio.run(main())
```

### Batch download

`download_pdfs()` downloads PDFs for a list of results. It skips any result that
already has `pdf_bytes`, and by default logs failures and keeps going (set
`stop_on_error=True` to raise on the first failure instead).

```python
import asyncio
from bharat_courts import JudgmentSearchClient

async def main():
    async with JudgmentSearchClient() as client:
        result = await client.search("anticipatory bail", page_size=25)

        downloaded = await client.download_pdfs(result.items)
        for j in downloaded:
            if j.pdf_bytes is not None:
                print(f"{len(j.pdf_bytes):>8} bytes  {j.title}")
            else:
                print(f"   (no PDF)  {j.title}")

asyncio.run(main())
```

!!! note "Some PDFs may be unavailable"
    Not every judgment on the portal has an uploaded PDF, and the download path can
    occasionally fail for a specific row. `download_pdfs()` skips and logs those by
    default rather than aborting the whole batch.

## Errors

`search()` and `search_all()` raise `CaptchaError` if the solver cannot produce a
valid CAPTCHA within `max_captcha_attempts` tries. An **empty** `SearchResult` is
distinct from a failure: it means the portal genuinely returned zero matching rows.

```python
from bharat_courts.hcservices.parser import CaptchaError

try:
    result = await client.search("some rare phrase")
except CaptchaError:
    print("Could not get past the CAPTCHA; try again or use a different solver.")
```

## See also

- [`Judgments` facade](facade.md) — the recommended entry point for judgment lookups;
  routes free-text queries here for you.
- [Historical archive](archive.md) — faster for bulk / historical pulls, but matches
  on title and structured fields, not full text.
- [CAPTCHA handling](captcha.md) — solvers used by all live clients.
- [Clients API reference](../reference/clients.md) — full signatures.
