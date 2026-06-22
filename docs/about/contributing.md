# Contributing & Developer Setup

bharat-courts is free, open-source software and contributions are welcome —
bug reports, fixes, more court coverage, better CAPTCHA solving, and docs all
help. This page gets you from a fresh clone to a green test run.

The code lives on GitHub at
[github.com/iamshouvikmitra/bharat-courts](https://github.com/iamshouvikmitra/bharat-courts).
Open issues and pull requests there.

!!! info "Audience"
    This is an engineer-facing page. If you just want to *use* the library,
    start at [Installation](../start/installation.md) and the
    [Quickstart](../start/quickstart.md). If you want to use it through an AI
    assistant, see the [lawyers' guides](../lawyers/index.md).

## Prerequisites

- **Python 3.11+** — check with `python3 --version`. If your system Python is
  older, use `python3.12` explicitly in the commands below.
- **git**

## Dev environment setup

Fork the repo on GitHub, then clone your fork:

```bash
# 1. Clone (swap in your fork's URL)
git clone https://github.com/<your-username>/bharat-courts.git
cd bharat-courts

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate     # Linux/macOS
# .venv\Scripts\activate      # Windows

# 3. Editable install with all extras (OCR + ONNX + CLI + archive + dev tools)
pip install -e ".[all]"

# 4. Verify everything works
pytest
ruff check . && ruff format --check .
```

`pip install -e ".[all]"` installs the package in editable mode with every
optional extra, so you can work on any backend — live clients, the archive, the
CLI — without reinstalling.

!!! tip "Older system Python"
    If `python3 --version` reports 3.10 or earlier, substitute `python3.12`
    when creating the virtual environment:

    ```bash
    python3.12 -m venv .venv
    ```

## Running tests

The unit suite is **250 tests and runs entirely offline** — no network, no
CAPTCHA, no AWS. It should pass on a fresh clone in seconds.

```bash
# Full unit suite (fast, offline)
pytest

# A single test file
pytest tests/test_hcservices_parser.py

# A single test
pytest tests/test_hcservices_parser.py::test_parse_case_status_json

# Verbose output
pytest -v
```

### Live integration tests

The `tests/integration/` directory holds **standalone scripts** that hit the
real eCourts portals and the real AWS Open Data buckets. They are **not
collected by `pytest`** (the default `python_files=test_*.py` pattern does not
match them), so you invoke them directly. They need network access, and the
portal-facing ones need a CAPTCHA solver (install the `[ocr]` extra, included in
`[all]`). Each script prints PASS/FAIL and exits non-zero on failure, which
makes them useful for pre-release validation.

```bash
python tests/integration/hcservices.py            # HC Services portal + CAPTCHA
python tests/integration/archive.py               # archive + facade vs real S3
python tests/integration/districtcourts.py        # District Courts portal
python tests/integration/calcuttahc_wpa_12886.py  # Calcutta HC regression case
```

See `tests/integration/README.md` for the full list and details.

!!! warning "Integration tests touch live services"
    Because they scrape real portals, integration runs are slower, rate-limited,
    and can fail for reasons outside your change (portal downtime, a CAPTCHA
    miss, an upstream HTML tweak). Treat a unit-suite pass as the bar for a PR;
    run the relevant integration script when you have changed a backend that
    talks to that portal.

## Linting and formatting

The project uses [ruff](https://docs.astral.sh/ruff/) for both linting and
formatting.

```bash
# Check for lint issues
ruff check .

# Auto-fix what ruff can fix
ruff check --fix .

# Check formatting without writing
ruff format --check .

# Reformat the codebase
ruff format .
```

Config lives in `pyproject.toml`: Python 3.11 target, 100-character line length,
rule sets `E`, `F`, `I`, `N`, `W`.

## Source layout

All package code is under `src/bharat_courts/` (a `src/` layout, which prevents
accidental imports of the working tree during development). The headline
modules:

| Path | What it holds |
|------|---------------|
| `models.py` | All DTO dataclasses (`Court`, `CaseInfo`, `CaseOrder`, `CauseListPDF`, `JudgmentResult`, `Judgment`, `SearchResult`) with `to_dict()` / `to_json()`. |
| `courts.py` | Static registry of every court + eCourts state codes; `get_court()`, `get_court_by_state_code()`, `infer_court_from_cnr()`. |
| `config.py` | Pydantic Settings with the `BHARAT_COURTS_` env prefix; a module-level `config` singleton. |
| `http.py` | `RateLimitedClient` wrapping httpx (retry, rate limiting, SSL bypass, browser-like headers) for the live clients. |
| `captcha/` | Pluggable solving: `CaptchaSolver` ABC → `ManualCaptchaSolver`, `OCRCaptchaSolver` (ddddocr), `ONNXCaptchaSolver`. |
| `hcservices/` | Primary live client for `hcservices.ecourts.gov.in`. |
| `districtcourts/` | Live client for `services.ecourts.gov.in` (700+ courts). |
| `calcuttahc/` | Direct-website client for `calcuttahighcourt.gov.in`. |
| `judgments/` | Live client for `judgments.ecourts.gov.in`. |
| `sci/` | Live client for `www.sci.gov.in` (homepage feed). |
| `archive/` | Opt-in (`[archive]` extra): DuckDB over the AWS Open Data parquet shards + PDF caching. |
| `facade.py` | `Judgments` — the federated `find()` / `fetch_pdf()` entry point that routes archive vs live. |
| `cli.py` | Click CLI entry point; command groups mirror the SDK module names. |

The clients in `hcservices/`, `districtcourts/`, `calcuttahc/`, and `judgments/`
each follow the same internal split — `client.py` (the public class),
`endpoints.py` (URL and form builders), `parser.py` (response parsers).

For deeper architectural background see [How it works](how-it-works.md) and the
[data sources](data-sources.md) page.

## Testing approach

Knowing how the suite is built makes it easier to add tests for your change:

- **HTTP is mocked with [respx](https://lundberg.github.io/respx/)**, which
  hooks into httpx natively. Parser tests feed recorded HTML/JSON fixtures from
  `tests/fixtures/` through the parsers.
- **CAPTCHA in tests** is handled by a custom `CaptchaSolver` subclass that
  returns a fixed string, so live-client tests never touch a real solver.
- **Archive tests** build **synthetic in-memory tars** and `respx`-mocked HTTP
  instead of hitting S3, and stub the DuckDB query / cache layer with
  `AsyncMock` + `unittest.mock.patch.object`.
- **Facade tests** stub both backends with `AsyncMock` so the routing decision
  matrix is exercised without touching either S3 or the live portal.

!!! note "respx caveat"
    respx does not support `host__icontains` matchers — use `url__regex`
    instead when matching by host.

## Areas where help is needed

A few concrete places where contributions would land well:

- **Better CAPTCHA solving** — ddddocr is ~75% accurate on the judgments portal;
  the ONNX solver is an alternative, but a fine-tuned model would help further.
- **District court reliability** — broader coverage testing across more
  states/complexes; `case_status_by_party` still has no pagination.
- **Supreme Court case search** — `SCIClient.search_by_year` /
  `search_by_party` are stubbed; the live `www.sci.gov.in` portal has a
  CAPTCHA-protected case-no/diary-no/party-name form that needs wiring up.
- **HC Services case history** — `case_status` does not return Pending/Disposed
  (or registration date / next hearing) because the SDK hits `showRecords`
  only; calling `o_civil_case_history.php` afterwards would fill in the rest.
- **More High Court coverage** — testing against courts beyond Delhi, Bombay,
  and Allahabad.
- **Documentation** — more examples and tutorials.

## Submitting changes

1. Fork the repo and create a branch: `git checkout -b my-feature`.
2. Make your changes.
3. Run `pytest` and `ruff check .` to confirm tests pass and the code is clean.
4. Commit with a descriptive message.
5. Open a pull request against
   [iamshouvikmitra/bharat-courts](https://github.com/iamshouvikmitra/bharat-courts).

Bug reports and feature requests are equally welcome on the
[issue tracker](https://github.com/iamshouvikmitra/bharat-courts/issues).

## License

bharat-courts is released under the [MIT License](https://github.com/iamshouvikmitra/bharat-courts/blob/main/LICENSE).
Note that the historical **archive data** itself is CC-BY-4.0 — attribute Dattam
Labs / the eCourts platform when you redistribute it. See
[Data sources](data-sources.md) for details.
