# Search by act

"Which pending cases are filed under the Negotiable Instruments Act, section 138, in
the Delhi High Court?" is one of the most common questions in Indian legal research.
The eCourts portals can answer it, but not directly: every court keeps its own act
list with its own codes and spellings, results arrive unpaged, and the 2024 criminal
codes renumbered everything. This guide covers the tools that deal with all of that.

For the generated API surface, see the [act search API reference](../reference/acts.md).

## Two questions, two answers

"Cases under an act" can mean two different things, and the SDK keeps them apart:

| You want | Use | Backend | A hit means |
|---|---|---|---|
| Cases **registered under** an act | `ActSearch.cases()` | HC Services / District Courts | The court recorded the case under that act |
| Judgments that **mention** an act | `ActSearch.judgments()` or `Judgments.find(act=...)` | Judgments portal | The act appears in the judgment text |

The first is the court's own record and finds cases whose title never names the act.
The second is a text match: broader, and it covers every High Court at once, but a
judgment that cites the NI Act in passing counts too.

The historical archive has no act data, so neither question can be answered from it
alone. `with_judgments=True` (below) joins live act-search results to the archive by CNR
instead.

## Quick start

```python
import asyncio
from bharat_courts import ActSearch


async def main():
    async with ActSearch() as s:
        result = await s.cases(
            act="NI Act",
            section="138",
            courts=["delhi", "allahabad"],
            status="Pending",
            year=2026,
        )

        for court, matches in result.resolution.items():
            print(court, "→", [f"{m.name} [{m.code}]" for m in matches])
        for court, error in result.errors.items():
            print(court, "failed:", error)

        print(len(result.hits), "cases")
        for hit in result.hits[:5]:
            c = hit.case
            print(hit.court.code, c.case_type, c.case_number, c.petitioner, "v", c.respondent)


asyncio.run(main())
```

Measured live (October 2026): "NI Act" resolved to code `18` in Delhi and `729` in
Allahabad, and returned 771 pending s.138 cases registered in 2026.

## What `ActSearch.cases()` does

For each court:

1. **Fetches the court's act list** (`list_acts`, no CAPTCHA). Lists are cached for a
   week under `~/.cache/bharat-courts/acts/`, per bench, because they differ even
   between benches of one High Court. Override the cache lifetime with
   `BHARAT_COURTS_ACTS_TTL_DAYS`.
2. **Resolves the act name against that list.** See [How names are resolved](#how-names-are-resolved).
3. **Searches every matching code × section × status.** One act often has several
   codes on one court: Delhi files 1996-Act arbitrations under three.
4. **Merges the hits**, one per case, each tagged with the court, act code, act name
   and section that found it.

`result.resolution` records what each court resolved the act to. An **empty list means
the act isn't on that court's list** (Allahabad, for instance, lists no Bharatiya Nyaya
Sanhita), not that the court has no such cases. Check it before concluding anything
from an empty result.

`result.errors` records failures per court. One court failing (a CAPTCHA that never
solves, a portal timeout) never discards the other courts' hits.

### Options

| Argument | Meaning |
|---|---|
| `act` | Act name as you'd type it: `"IPC"`, `"NI Act"`, `"Negotiable Instruments Act, 1881"` |
| `courts` | Court codes or `Court` objects, or `"all-hc"` for every High Court's principal bench |
| `section` | One section or a list. Matched **exactly** (`"13"` doesn't find 138); letters, digits and spaces only, so search `["138", "141"]`, not `"138/141"` |
| `status` | `"Pending"`, `"Disposed"` or `"Both"` (two searches) |
| `year` | Registration year or `(start, end)`, applied after download |
| `include_successor` | Also search the code that replaced it (see below) |
| `all_benches` | Search every bench of each court, not just the principal |
| `with_judgments` | Attach archived judgments to disposed hits (needs the `[archive]` extra) |
| `concurrency` | Searches in flight at once (default 2) |

### What it costs

Every search is one CAPTCHA solve: courts × act codes × sections × statuses. The
plan is logged at INFO before anything is sent:

```
Act search: 4 searches over 2 court(s), ~4 CAPTCHA solves
```

The portal returns all matches in one response, with no paging. Delhi's IPC s.302
disposed list is about 16,000 rows (6 MB). Narrow by `section` where you can. `year`
helps the output, but not the download.

## The 2024 criminal codes

From 1 July 2024, new cases cite the Bharatiya Nyaya Sanhita (BNS), Bharatiya Nagarik
Suraksha Sanhita (BNSS) and Bharatiya Sakshya Adhiniyam (BSA) instead of the IPC, CrPC
and Indian Evidence Act, under different section numbers. A search for "IPC 302"
alone misses recent murder cases filed as "BNS 103".

`include_successor=True` adds the successor sections automatically:

```python
result = await s.cases(
    act="IPC",
    section="302",
    courts="gujarat",
    status="Disposed",
    include_successor=True,
)
# searches IPC s.302 and BNS s.103 — hits say which via hit.act_key ("ipc" / "bns")
```

The mapping is available on its own, too:

```python
from bharat_courts import successor_sections

for m in successor_sections("ipc", "498A"):
    print(m.new_act, m.new_section, "search as", m.new_section_base)
# bns 85 search as 85
# bns 86 search as 86
```

`new_section` is as the source table prints it (`"103(1)"`), and `new_section_base` is
what a portal's section box accepts (`"103"`). The table comes from the correspondence
tables published by the Central Academy for Police Training, Bhopal. It is generated
by `scripts/build_crosswalk.py`, and each mapping cites its source page.

## Joining to the archive

For disposed cases, `with_judgments=True` looks each hit up in the historical archive
by CNR and attaches the `Judgment` (with its PDF reference) as `hit.judgment`:

```python
result = await s.cases(
    act="IPC",
    section="302",
    courts="gujarat",
    status="Disposed",
    year=2024,
    with_judgments=True,
)
archived = [h for h in result.hits if h.judgment]
```

This runs one archive query per court and decision year, not one per case. The archive
lags the portal by a few months and its coverage varies by court and year, so expect
gaps. The INFO log reports the coverage per court-year (in the live run above:
`Gujarat High Court 2024 — 27 of 1224 in the archive`). Hits that carry a trial
court's CNR rather than the High Court's are skipped.

## Judgments that mention an act

```python
async with ActSearch() as s:
    hits = await s.judgments(act="Negotiable Instruments Act", section="138", text="cheque")
```

or through the facade:

```python
async with Judgments() as j:
    hits = await j.find(act="Negotiable Instruments Act", section="138", limit=20)
```

The portal accepts letters and spaces only for the act, so digits and punctuation are
dropped before sending: `"Negotiable Instruments Act, 1881"` becomes
`"Negotiable Instruments Act"`. Partial names match. Prefer the full name over an
abbreviation that judgment text may not use.

`find(act=...)` always routes to the live portal. Forcing `source="archive"` with
`act=` raises `ValueError` rather than quietly falling back to a title match.

## How names are resolved

`bharat_courts.acts.resolve(query, act_list)` is the piece that turns what you type
into a court's codes. It is deliberately conservative:

- **Curated acts.** About 50 frequently litigated central acts are known with their
  aliases: `IPC`, `CrPC`, `NI Act`, `NDPS`, `POCSO`, `SARFAESI`, and so on. A query
  naming one matches the court's entries for that act by normalised name. Case,
  punctuation, a leading "the", the word "act", abbreviation brackets and plurals
  are ignored, so "INDIAN PENAL CODE1", "I.P.C(POLICE)" and "PENAL CODE, 1860" all
  resolve as IPC.
- **Years must agree.** "Motor Vehicles Act, 1939" never answers for the 1988 Act, and
  "Arbitration" means the 1996 Act. Ask for "Arbitration Act 1940" to get the old one.
- **Near-misses are allowed, narrowly.** Misspellings on court lists ("Domestic
  Violance", "Bharatiya Nyay Sanhita") still match, but anything that adds a qualifier
  ("Rules", "Amendment", "Order") never does. A case under the NDPS Rules is not a case
  under the NDPS Act.
- **Anything else** is matched directly against the court's names: an exact match if
  there is one, otherwise every entry containing all your words. That fallback is
  broad, so check `result.resolution`.

To see what a name resolves to before spending CAPTCHAs:

```python
async with ActSearch() as s:
    for m in await s.resolve("arbitration", "delhi"):
        print(m.code, m.name, m.tier)
```

```bash
bharat-courts acts resolve "arbitration" --court delhi
```

## District courts

`ActSearch` covers High Courts. For district courts, use the client directly. Within a
court complex, an act search covers **one establishment** at a time, and cases sit
where they're tried: at one Delhi complex, NI Act cheque cases are with the chief
metropolitan magistrate (7,521) rather than the sessions court (23).

```python
from bharat_courts import DistrictCourtClient
from bharat_courts.acts import resolve

async with DistrictCourtClient() as dc:
    ests = await dc.list_establishments("26", "1", "1260001")
    for est in ests:
        acts = await dc.list_acts("26", "1", "1260001", est)
        for m in resolve("NI Act", acts):
            cases = await dc.case_status_by_act(
                state_code="26",
                dist_code="1",
                court_complex_code="1260001",
                est_code=est,
                act_code=m.code,
                section="138",
            )
```

The CLI does this loop for you with `--all-establishments`.

## Command line

```bash
# What does the court call it?
bharat-courts acts resolve "NI Act" --court delhi

# Cases registered under an act, across courts
bharat-courts acts search --act "NI Act" --section 138 --courts delhi,allahabad --year 2026
bharat-courts acts search --act IPC --section 302 --courts all-hc --status disposed \
    --include-successor --with-judgments

# Where did a section go?
bharat-courts acts successor crpc 438        # CRPC 438 → BNSS 482

# One court, by code
bharat-courts hcservices acts delhi --search negotiable
bharat-courts hcservices search-by-act delhi --act-code 18 --section 138 --status both

# District courts, every establishment of a complex
bharat-courts districtcourts search-by-act --state 26 --dist 1 --complex 1260001 \
    --all-establishments --act "NI Act" --section 138

# Judgments that mention an act
bharat-courts judgments search --act "Negotiable Instruments Act" --section 138
bharat-courts find --act "Negotiable Instruments Act" --section 138
```

Add `--json` before the subcommand for machine-readable output.

## Low-level methods

| Method | CAPTCHA | Notes |
|---|---|---|
| `HCServicesClient.list_acts(court, *, bench_code="1", search="")` | No | Code → name for one bench |
| `HCServicesClient.case_status_by_act(court, *, act_code, section="", status_filter="Pending", bench_code="1", year=None, dedupe=True)` | Yes | `"Both"` = two requests |
| `DistrictCourtClient.list_acts(state, dist, complex, est="", search="")` | No | Per establishment |
| `DistrictCourtClient.case_status_by_act(*, state_code, dist_code, court_complex_code, est_code="", act_code, section="", status_filter="Pending", year=None, dedupe=True)` | Yes | Section max 15 chars |
| `JudgmentSearchClient.search(search_text="", *, act="", section="", ...)` | Yes | Text may be empty with `act` |
| `JudgmentSearchClient.list_acts()` | Yes | The portal's ~2,000-name act vocabulary |
