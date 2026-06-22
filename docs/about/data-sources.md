# Data Sources & Licensing

bharat-courts does not host any court data of its own. It is a thin, open-source
layer over public Indian court data — the official eCourts portals on one side,
and a public AWS Open Data archive on the other. This page explains exactly where
the data comes from, how current it is, how it is licensed, and how to attribute it
when you republish it.

For the mechanics of how the two backends are wired together, see
[How it works](how-it-works.md).

## Two kinds of source

bharat-courts reads from two complementary kinds of source:

- **Live sources** — the official eCourts and court websites. These reflect the
  *current* state of a case: status, next hearing, cause lists, freshly uploaded
  orders. They are CAPTCHA-gated and rate-limited.
- **Historical archive** — two public AWS Open Data S3 buckets mirroring decided
  judgments back to 1950. No CAPTCHA, no rate limits, but the data lags real time
  by a couple of months.

!!! tip "Which one answers my question?"
    Use the **live** sources for "what is happening *now*" — case status, next
    hearing date, today's cause list, an order uploaded this week. Use the
    **archive** for historical research and bulk retrieval of *decided* judgments.
    The `Judgments` facade picks between them for you on most queries.

## Live sources

These are the official portals bharat-courts scrapes. Each has its own client in
the SDK.

| Source | Portal | Client | What it provides |
|---|---|---|---|
| High Court Services | [hcservices.ecourts.gov.in](https://hcservices.ecourts.gov.in) | `HCServicesClient` | High Court case status, orders, cause lists, bench/case-type discovery |
| District Courts | [services.ecourts.gov.in](https://services.ecourts.gov.in) | `DistrictCourtClient` | District court case status, orders, cause lists across 700+ court complexes |
| Judgment Search | [judgments.ecourts.gov.in](https://judgments.ecourts.gov.in) | `JudgmentSearchClient` | Full-text keyword search of High Court judgments, with PDF download |
| Supreme Court | [www.sci.gov.in](https://www.sci.gov.in) | `SCIClient` | The homepage "Latest Judgements / Orders" feed and PDF download |
| Calcutta High Court | [calcuttahighcourt.gov.in](https://calcuttahighcourt.gov.in) | `CalcuttaHCClient` | Order/judgment search direct from the court's own site (better Calcutta HC PDF coverage from September 2020 onwards) |

!!! info "Update cadence: live = real-time"
    Live sources are queried on demand and reflect whatever the portal shows at
    that moment. There is no caching delay on the data itself — if the court has
    updated a record, the live client sees it.

!!! note "Known live-source limitations"
    A few flows are not yet wired up, and bharat-courts is honest about this rather
    than guessing:

    - The Supreme Court client surfaces the recent-judgments feed and PDF download;
      `SCIClient.search_by_year(...)` and `search_by_party(...)` raise
      `NotImplementedError` (the legacy host they used is permanently offline and the
      replacement form is CAPTCHA-gated).
    - The HC Services `showRecords` endpoint does not return case *status*,
      `registration_date`, `judges`, or `next_hearing_date`, so those fields stay
      empty on results from that path.

## Historical archive (AWS Open Data)

For research and bulk work, `ArchiveClient` reads two public S3 buckets in the
AWS Open Data programme. **No CAPTCHA, no rate limits, no AWS account needed.**
They require the archive extra (`pip install 'bharat-courts[archive]'`).

| Bucket | Contents | Registry |
|---|---|---|
| `indian-supreme-court-judgments` | Supreme Court of India, **1950 → present** | [registry.opendata.aws](https://registry.opendata.aws/indian-supreme-court-judgments/) |
| `indian-high-court-judgments` | 25 High Courts | [registry.opendata.aws](https://registry.opendata.aws/indian-high-court-judgments/) |

Both buckets are:

- hosted in the **`ap-south-1`** (Mumbai) region,
- licensed **CC-BY-4.0**,
- maintained by **Dattam Labs**.

Judgment metadata lives in partitioned parquet files (queried with DuckDB);
the PDFs are served as direct downloads (High Court) or per-year tar archives
(Supreme Court). Both layers cache to disk under
`~/.cache/bharat-courts/archive/`.

!!! info "Update cadence: archive lags by 2–3 months"
    - The Supreme Court bucket updates **bi-monthly**.
    - The High Court buckets update **quarterly**.

    A judgment delivered in the last 2–3 months may not be in the archive yet. If a
    structured archive query returns nothing for a recent year, retry on the live
    portal — for example `Judgments().find(..., source="live")`, or a direct
    `JudgmentSearchClient` / `HCServicesClient` lookup.

## Coverage at a glance

| Court tier | Coverage | Available via |
|---|---|---|
| Supreme Court of India | Live recent-judgments feed; archive **1950 → present** | `SCIClient`, `ArchiveClient`, `Judgments` |
| High Courts | **25 High Courts** (live case data + archive) | `HCServicesClient`, `JudgmentSearchClient`, `CalcuttaHCClient`, `ArchiveClient`, `Judgments` |
| District Courts | **700+ court complexes** across 36 states/UTs (live only) | `DistrictCourtClient` |

The full list of High Court codes is in the
[Courts reference](../reference/courts.md).

## Licensing

### The bharat-courts software: MIT

The bharat-courts library itself — the SDK, CLI, and the bundled AI-agent skill —
is released under the **MIT License**. You are free to use it commercially, modify
it, and redistribute it, subject to the MIT terms.

### The data: terms of the originating source

The *software* licence does not relicense the *data*. The data carries its own
terms, which depend on where it came from:

- **Archive data (both AWS Open Data buckets)** is licensed **CC-BY-4.0**.
- **Live portal data** is retrieved directly from the official eCourts / court
  websites and is subject to those portals' own terms of use.

## Attribution

When you redistribute or republish data obtained through bharat-courts, attribute
the originating source — this is a condition of the CC-BY-4.0 licence on the
archive, and good practice for the live portals.

- **Archive (CC-BY-4.0):** attribute **Dattam Labs** (the bucket maintainers) and
  the underlying **eCourts** platform. Retaining a link to the relevant AWS Open
  Data registry page is the simplest way to satisfy the attribution requirement.
- **Live portals:** credit the relevant **eCourts** portal or court website as the
  source.

!!! tip "Attributing in practice"
    A short credit line is enough — for example: *"Judgment data via the Indian
    High Court Judgments / Supreme Court Judgments AWS Open Data buckets
    (CC-BY-4.0), maintained by Dattam Labs, sourced from the eCourts platform."*

## Disclaimer

!!! warning "Read this before relying on the data"
    - **Not affiliated with the judiciary.** bharat-courts is an independent,
      open-source tool. It is **not** affiliated with, endorsed by, or operated by
      the Supreme Court of India, any High Court, any District Court, the eCourts
      platform, or any government body.
    - **Provided as-is, from public sources.** Data is surfaced as published by the
      official portals and the public archive. bharat-courts does not alter the
      substance of records; accuracy, completeness, and timeliness depend entirely
      on the upstream source.
    - **Verify mission-critical information against the official record.** For
      anything that matters — limitation periods, hearing dates, the operative text
      of an order or judgment — confirm against the official court record or a
      certified copy before relying on it. The archive's freshness gap and the
      occasional empty field on live results make independent verification
      essential.
    - **Not legal advice.** bharat-courts is a data-access tool. Nothing it returns,
      and nothing in this documentation, constitutes legal advice.

## See also

- [How it works](how-it-works.md) — the architecture behind the live/archive split.
- [Courts reference](../reference/courts.md) — every supported court and its codes.
