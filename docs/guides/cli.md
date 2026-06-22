# Command-line interface

Everything the SDK can do is also available from your terminal via the
`bharat-courts` command. The CLI is a thin wrapper over the same async clients —
no scripting required for one-off lookups, ad-hoc research, or shell pipelines.

The command tree maps one-to-one onto the SDK modules:

```text
bharat-courts version
bharat-courts courts [--type all|hc|sc]
bharat-courts install-skills
bharat-courts find ...               # the CLI twin of the Judgments facade

bharat-courts hcservices ...         # hcservices.ecourts.gov.in
bharat-courts districtcourts ...     # services.ecourts.gov.in
bharat-courts calcuttahc ...         # calcuttahighcourt.gov.in
bharat-courts judgments ...          # judgments.ecourts.gov.in
bharat-courts sci ...                # www.sci.gov.in
bharat-courts archive ...            # AWS Open Data archive
```

!!! info "Install the CLI extra"

    The CLI ships behind its own optional dependency. Install it (and, for the
    `archive` commands, the archive extra) with:

    ```bash
    pip install 'bharat-courts[cli]'
    pip install 'bharat-courts[cli,archive,ocr]'   # everything you'll want for daily use
    ```

    See [Installation](../start/installation.md) for the full matrix of extras.

## Global flags

These flags work on **every** subcommand and must come *before* the command
name (they belong to the root `bharat-courts` group):

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | off | Emit machine-readable JSON instead of human-readable text. |
| `--captcha-attempts N` | `5` | Max CAPTCHA solve attempts per call. Applies to the `judgments` and `calcuttahc` groups; `hcservices`/`districtcourts` use a fixed internal budget. |
| `-v`, `--verbose` | off | Turn on INFO-level SDK logging (routing decisions, retries) on stderr. |
| `--version` | — | Print the version and exit. |
| `--help` | — | Show help for any command or group. |

```bash
bharat-courts --json find --judge chandrachud --year 2018-2024 --court sci
bharat-courts --verbose hcservices benches delhi
bharat-courts --version
```

!!! tip "`--json` is built for pipelines"

    With `--json`, the CLI prints a single, indented JSON document and nothing
    else — no banners, no progress chatter. That makes it safe to pipe straight
    into `jq`, write to a file, or load into another tool:

    ```bash
    bharat-courts --json find --court delhi --year 2020 --limit 100 \
      | jq '.[] | {date: .decision_date, title}'

    bharat-courts --json archive count --court sci > sci_counts.json
    ```

    Every model serialises via `to_dict(exclude_none=True)`, so dates come back
    as ISO strings and empty fields are dropped.

## Top-level commands

### `find` — the federated search command

`bharat-courts find` is the command-line twin of the [`Judgments`
facade](facade.md). You describe the data you want; it picks the archive or the
live portal for you and prints a uniform list of judgments.

| Option | Description |
|--------|-------------|
| `--text` | Free-text keyword search. On its own, routes to the **live** portal (only it does full-body search). |
| `--court` | Court code: `sci`, `delhi`, `bombay`, etc. |
| `--year` | Single year (`2020`) or an inclusive range (`2018-2024`). |
| `--judge` | Substring on the judge name (archive). |
| `--party` | Substring on petitioner/respondent (SCI) or title (HC). |
| `--citation` | SCI citation substring. |
| `--cnr` | A CNR — auto-routes to the archive via its 4-letter prefix. |
| `--source` | `auto` (default), `archive`, or `live` — override the automatic routing. |
| `--limit` | Max results to return (default `20`). |

The routing in `auto` mode mirrors the facade exactly:

| Filters supplied | Backend chosen |
|------------------|----------------|
| `--cnr` | archive (prefix → court → partition) |
| `--text` only | live |
| structured only (court/year/judge/party/citation) | archive |
| `--text` + structured | archive (text folds into a title-match) |
| nothing | error |

```bash
# Structured filters → archive, no CAPTCHA
bharat-courts find --judge chandrachud --year 2018-2024 --court sci --limit 10

# Free text → live full-body search (needs a CAPTCHA solver installed)
bharat-courts find --text "right to privacy" --limit 5

# CNR alone → archive, prefix-routed
bharat-courts find --cnr DLHC010230802020
```

Human output:

```text
Found 3 judgment(s):

[archive] Justice K.S. Puttaswamy (Retd.) vs Union Of India
  CNR ... · Civil Appeal No. ... · (2017) 10 SCC 1
  Court: Supreme Court of India
  Decided: 2017-08-24
  Bench: D.Y. Chandrachud, ...
  Outcome: Allowed
```

The same call with `--json` returns a JSON array of `Judgment` objects, each
carrying a `source` field (`"archive"` or `"live"`) so you can tell where every
row came from.

### `courts` — list the court registry

```bash
bharat-courts courts                 # all 30 courts
bharat-courts courts --type hc       # High Courts only
bharat-courts courts --type sc       # Supreme Court only
```

`--type` accepts `all` (default), `hc`, or `sc`. Human output is a table of
**Code / Name / State Code / Type**; `--json` returns the same as an array of
`Court` dicts. Use the **Code** column for the `--court` / court-code arguments
elsewhere.

### `install-skills` — wire up your AI assistant

```bash
bharat-courts install-skills
```

Copies the bundled Agent Skill into `.claude/skills/bharat-courts/` in the
current directory, so a Claude-based assistant can call the SDK on your behalf
in plain English. See the [lawyer guides](../lawyers/claude-code.md) for what to
do next.

## `hcservices` — High Court Services portal

Commands for `hcservices.ecourts.gov.in`. Most take a **court code** as a
positional argument (run `bharat-courts courts --type hc` to list them). The
discovery commands (`benches`, `case-types`) need no CAPTCHA; the rest do, and
are auto-retried.

| Command | Purpose | Key options |
|---------|---------|-------------|
| `benches COURT` | List benches for a High Court | — |
| `case-types COURT` | List case-type codes for a bench | `--bench` (default `1`) |
| `search COURT` | Case status by case number | `--case-type` ·`--case-number` · `--year` (all required) · `--bench` |
| `search-by-party COURT` | Case status by party name | `--party` · `--year` (both required) · `--status pending\|disposed\|both` · `--bench` |
| `orders COURT` | Orders for a case | `--case-type` · `--case-number` · `--year` (required) · `--bench` · `--download DIR` |
| `cause-list COURT` | Cause-list PDFs | `--date DD-MM-YYYY` · `--criminal` · `--bench` · `--download DIR` |

```bash
# Discover bench codes, then case-type codes (no CAPTCHA)
bharat-courts hcservices benches bombay
bharat-courts hcservices case-types delhi --bench 1

# Look up a writ petition by its numeric case-type code
bharat-courts hcservices search delhi --case-type 134 --case-number 1 --year 2024

# All orders, saving the PDFs to ./orders/
bharat-courts hcservices orders delhi \
  --case-type 134 --case-number 1 --year 2024 --download ./orders/
```

`benches` and `case-types` print `code  name` pairs (or a JSON object with
`--json`). The `--download` option on `orders` and `cause-list` writes each PDF
to the directory and, in JSON mode, adds a `pdf_local_path` field to each row.

!!! note "Numeric case-type codes"

    `--case-type` wants the **numeric** code from `case-types`, e.g. `134` for
    `W.P.(C)` on Delhi HC — not the label. Always run `case-types` first.

## `districtcourts` — District Courts portal

Commands for `services.ecourts.gov.in` (700+ court complexes). District courts
have no static codes; you discover the hierarchy
**State → District → Complex → Establishment** with the listing commands, then
feed those codes into the search/orders/cause-list commands.

| Command | Purpose | Required options |
|---------|---------|------------------|
| `states` | List states/UTs | — |
| `districts` | Districts in a state | `--state` |
| `complexes` | Court complexes in a district | `--state` · `--dist` |
| `establishments` | Establishments in a complex | `--state` · `--dist` · `--complex` |
| `case-types` | Case-type codes for a court | `--state` · `--dist` · `--complex` (`--est` optional) |
| `courts` | Courts for cause-list lookup | `--state` · `--dist` · `--complex` (`--est` optional) |
| `search` | Case status by case number | `--state` · `--dist` · `--complex` · `--case-type` · `--case-number` · `--year` (`--est` optional) |
| `search-by-party` | Case status by party | `--state` · `--dist` · `--complex` · `--party` · `--year` (`--est` optional, `--status`) |
| `orders` | Orders for a case | as `search`, plus `--download DIR` |
| `cause-list` | Cause-list entries | `--state` · `--dist` · `--complex` · `--court-no` (`--est`, `--court-name`, `--date`, `--criminal`) |

```bash
# Walk the hierarchy
bharat-courts districtcourts states
bharat-courts districtcourts districts --state 8                  # Bihar
bharat-courts districtcourts complexes --state 8 --dist 1         # Patna
bharat-courts districtcourts case-types --state 8 --dist 1 --complex 1080010 --est 2

# Search using the discovered codes (case-type is the compound "<code>^<est>")
bharat-courts districtcourts search \
  --state 8 --dist 1 --complex 1080010 --est 2 \
  --case-type "89^2" --case-number 100 --year 2024

# Cause list — --court-no comes from the `courts` subcommand
bharat-courts districtcourts cause-list \
  --state 8 --dist 1 --complex 1080010 --est 2 \
  --court-no "1@2" --date 20-03-2026
```

!!! warning "Pass compound codes verbatim"

    The portal returns case-type codes like `89^2` and court codes like `1@2`.
    Pass them back exactly as given — do not strip the `^N` or `@N` suffix.
    `--court-name` is auto-resolved from `--court-no` if you leave it blank.

`--status` (on `search-by-party`) accepts `pending`, `disposed`, or `both`
(default `both`).

## `calcuttahc` — Calcutta High Court website

A single command against `calcuttahighcourt.gov.in`, which has better PDF
coverage for Calcutta HC cases than the eCourts portal.

| Command | Purpose | Options |
|---------|---------|---------|
| `search` | Search orders/judgments by case number | `--case-type` · `--case-number` · `--year` (required) · `--establishment` · `--download DIR` |

`--establishment` is one of `appellate` (default), `original`, `jalpaiguri`, or
`portblair`.

```bash
bharat-courts calcuttahc search \
  --case-type 12 --case-number 12886 --year 2024 \
  --establishment appellate --download ./calcutta/
```

In JSON mode the output is an object with `case_info` and an `orders` array;
downloaded PDFs add a `pdf_local_path` to each order. CAPTCHA is auto-retried
(tune with the global `--captcha-attempts`).

## `judgments` — eCourts judgment search

Full-text search against `judgments.ecourts.gov.in`. CAPTCHA-gated.

| Command | Purpose | Key options |
|---------|---------|-------------|
| `search` | One page of results | `--text` (required) · `--page` · `--page-size` · `--search-opt PHRASE\|ANY\|ALL` · `--court-type` · `--download DIR` |
| `search-all` | Walk every page | `--text` (required) · `--page-size` · `--max-pages` (0 = all) · `--search-opt` · `--court-type` · `--download DIR` |

`--court-type` is `2` for High Courts (default) or `3` for the Supreme Court
report. `--search-opt` controls phrase matching.

```bash
# First page of phrase results
bharat-courts judgments search --text "right to privacy" --page-size 25

# Walk up to 5 pages and download every PDF
bharat-courts judgments search-all \
  --text "land acquisition" --max-pages 5 --download ./judgments/
```

The `search` JSON output wraps the items in pagination metadata
(`total_count`, `page`, `page_size`, `has_next`, `total_pages`, `items`);
`search-all` returns `{"total_items": N, "items": [...]}`.

## `sci` — Supreme Court feed

| Command | Purpose | Options |
|---------|---------|---------|
| `recent` | Most recent SC judgments (homepage feed) | `--limit` (max 50) · `--download DIR` |

No CAPTCHA — this scrapes the "Latest Judgements / Orders" feed on
`www.sci.gov.in`.

```bash
bharat-courts sci recent --limit 10
bharat-courts sci recent --limit 50 --download ./sci/
```

!!! note "Recent feed only"

    The SCI client only exposes the homepage feed today; case-number and
    party-name search are not yet wired up. For older Supreme Court matters,
    use `bharat-courts archive` or `bharat-courts find --court sci`.

## `archive` — historical AWS Open Data archive

Offline-friendly queries over the public S3 buckets (SCI 1950→present + 25 HCs).
No CAPTCHA, no rate limits. Requires the `archive` extra — every command in this
group prints an install hint and exits non-zero if it is missing.

| Command | Purpose | Key options |
|---------|---------|-------------|
| `query` | Search metadata | `--court` · `--year` · `--judge` · `--party` · `--citation` · `--cnr` · `--limit` |
| `get` | Look up one CNR; optionally save its PDF | `--cnr` (required) · `--pdf` · `--out` · `--language` |
| `download` | Pre-warm the cache (SCI year tars only) | `--court` (default `sci`) · `--year` (required) · `--language` |
| `cache` | Show cache stats or clear it | `--clear` |
| `count` | Row counts per bucket | `--court` · `--year` |

```bash
# Every Delhi HC judgment by a named judge in a date range
bharat-courts archive query --court delhi --judge "sanjeev" --year 2018-2022 --limit 50

# Resolve a CNR and save its PDF (SCI honours --language)
bharat-courts archive get --cnr ESCR010000301950 --pdf --out ./judgment.pdf
bharat-courts archive get --cnr DLHC010230802020 --pdf --out ./pdfs/

# Pre-warm a whole SCI year before a batch of fetches
bharat-courts archive download --court sci --year 2020

# How many rows are in the archive?
bharat-courts archive count --court sci --year 2020

# Cache housekeeping
bharat-courts archive cache
bharat-courts archive cache --clear
```

`get` without `--pdf` prints (or JSON-emits) just the metadata for the CNR.
`download` only supports SCI year tars — High Court PDFs are fetched on demand
by `get`, so `download --court delhi` will refuse with a clear message.

!!! info "Archive freshness"

    The buckets lag live filings by 2–3 months (SCI updates bi-monthly, HCs
    quarterly). For very recent judgments, use the live commands above or
    `bharat-courts find` and let routing decide. See the
    [Archive guide](archive.md) for cache sizing and language codes.

## Where next

- [Quickstart](../start/quickstart.md) — the five-minute tour of the SDK and CLI.
- [The `Judgments` facade](facade.md) — the Python equivalent of `find`, with
  the full routing matrix.
- [Configuration](../start/configuration.md) — environment variables for cache
  size, metadata TTL, and rate limits.
