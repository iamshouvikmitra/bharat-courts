# Integration tests

Live end-to-end checks that hit real external services (eCourts portals, AWS
Open Data buckets). **Not run by default** — they're slow, need network, and
depend on third-party portals that change shape underneath us. The same
scripts power the daily [Live E2E monitor](#scheduled-monitor-ci).

| Script | Backend | Hits | ~Runtime |
|---|---|---|---|
| `hcservices.py` | `HCServicesClient` | `hcservices.ecourts.gov.in` | 45–90s |
| `districtcourts.py` | `DistrictCourtClient` | `services.ecourts.gov.in` | 60–120s |
| `judgments.py` | `JudgmentSearchClient`, facade (live route) | `judgments.ecourts.gov.in` | ~30s |
| `calcuttahc.py` | `CalcuttaHCClient` (+ HC Services cross-check) | `calcuttahighcourt.gov.in` | ~40s |
| `sci.py` | `SCIClient` | `www.sci.gov.in` | ~5s |
| `archive.py` | `ArchiveClient`, facade (archive route) | S3 `indian-{supreme,high}-court-judgments` | 30–100s cold |
| `cli.py` | `bharat-courts` CLI, every command group | S3 + portals | ~60s |

`_common.py` is the shared harness (not a script): `Check` / `Suite`, daily
rotation, `first_working`, the JSON summary writer.

## Running

```bash
source .venv/bin/activate
pip install -e '.[all]'

python tests/integration/hcservices.py
python tests/integration/districtcourts.py
python tests/integration/judgments.py
python tests/integration/calcuttahc.py
python tests/integration/sci.py
python tests/integration/archive.py
python tests/integration/cli.py

# Reproduce a specific day's rotation (the seed is printed in every report)
E2E_SEED=739914 python tests/integration/hcservices.py

# Also write the machine-readable summary the CI monitor renders
E2E_SUMMARY_JSON=/tmp/hc.json python tests/integration/hcservices.py
```

Each script prints one line per check and exits non-zero if any check
**FAIL**s. Three verdicts:

| Verdict | Meaning |
|---|---|
| `PASS` | The SDK did what it claims against live data. |
| `FAIL` | It did not — the backend is broken (or a check's assumption is). Fails the script. |
| `SKIP` | The *portal's own backend* answered with an outage page (`Connection to server failed try after some time`, `Unable to connect to server`). The SDK sent a well-formed request and classified the response correctly, but can't be judged further. Does **not** fail the script; still listed so a week-long portal outage stays visible. |

## How the checks are built

**Rotation, not pinning.** Courts, states and search phrases come from pools
and rotate daily (`_common.rotate`, seeded from the date or `E2E_SEED`). Over
~3 weeks the HC Services suite has started from all 20 High Courts in its pool.
This was prompted by Delhi HC silently stopping to publish cause lists on HC
Services in Oct 2026 — a hard-coded `delhi` check failed for days while 19
other courts were fine.

**Fall-through.** Within a check, `first_working` tries candidates in rotation
order until one yields data and records what every candidate returned, so the
report shows "gauhati 26-10: 0 PDFs, gauhati 23-10: 2 PDFs" rather than a bare
pass. A check fails only when *every* candidate fails.

**Chaining.** Later checks feed off earlier results instead of hand-picked
cases: the party search's rows drive the case-number lookup, the CNR case
detail, court orders, the order PDF and the advocate search. Nothing in the
HC Services or District Courts suites depends on a specific case still
existing.

**One regression anchor.** `calcuttahc.py` keeps WPA 12886/2024 as a fixed
known-good case (CNR, decision date, order count asserted) *and* adds a
rotating WPA drawn from a live party search.

## Coverage map

What each public surface is exercised by. Anything not listed here is not
monitored live.

| SDK surface | Script · check |
|---|---|
| `courts` registry: `get_court`, `get_court_by_state_code`, `infer_court_from_cnr`, `list_high_courts` | hcservices · Court registry |
| `HCServicesClient.list_benches` / `list_case_types` | hcservices · Bench listing, Case type listing; cli |
| `HCServicesClient.cause_list` | hcservices · Cause list PDFs |
| `HCServicesClient.case_status_by_party`, `dedupe_by_cnr` | hcservices · Case status by party; calcuttahc · Rotating WPA |
| `HCServicesClient.case_status` (by number, incl. `bench_code`) | hcservices · Case status by number; calcuttahc · Cross-check |
| `HCServicesClient.case_status_by_cnr` → `CaseDetail` (`casedetail.parse_case_detail`) | hcservices · Case detail by CNR |
| `HCServicesClient.court_orders` / `download_order_pdf` | hcservices · Court orders + order PDF |
| `HCServicesClient.advocate_search` | hcservices · Advocate search |
| `DistrictCourtClient.list_states` + `DISTRICT_STATES` drift | districtcourts · States |
| `list_districts` / `list_complexes` / `parse_complex_value` / `list_establishments` / `list_case_types` | districtcourts · cascade checks; cli |
| `list_cause_list_courts` / `cause_list` | districtcourts · Cause-list courts + cause list |
| `DistrictCourtClient.case_status_by_party` | districtcourts · Case status by party |
| `DistrictCourtClient.case_status_by_cnr` → `CaseDetail` | districtcourts · Case detail by CNR |
| `DistrictCourtClient.court_orders` | districtcourts · Court orders |
| `JudgmentSearchClient.search` (HC and SCR), `search_all`, `download_pdf` (two rows must differ — `val` indexing) | judgments |
| `facade.live_to_judgment`; `Judgments.find` live route; `fetch_pdf(live)` → `NotImplementedError` | judgments · last three checks |
| `CalcuttaHCClient.search_orders` / `download_order_pdf` | calcuttahc |
| `SCIClient.list_recent_judgments` / `download_pdf`; `search_by_*` → `NotImplementedError` | sci |
| `ArchiveClient.search`, `iter_judgments`, `count`, `fetch_pdf` (HC direct GET + SCI tar), `cache_info`; parquet cache; CNR routing | archive |
| `Judgments.find` archive routes (structured / CNR / mixed / forced) + `ValueError` on no filters; `fetch_pdf(cnr)` | archive · Facade routing |
| Models: `to_dict` / `to_json` round-trip incl. a live `CaseDetail` | hcservices · Model JSON round-trip |
| `OCRCaptchaSolver` | hcservices · OCR CAPTCHA solver (plus every CAPTCHA-gated check) |
| CLI: `version`, `courts`, `hcservices benches/case-types`, `districtcourts states/districts`, `archive count/query/get/cache`, `find --cnr` / `--text`, `sci recent` | cli |

Not covered live (yet): `HCServicesClient.advocate_cause_list` (needs a bar
code), `DistrictCourtClient.case_status` by number (the CNR path covers the
same page), `ONNXCaptchaSolver` (downloads a model from Hugging Face),
`ManualCaptchaSolver` (interactive by design).

## Why not pytest?

- They hit external services, so unreliable as a default test gate.
- Pytest's default discovery (`test_*.py`) doesn't match these filenames, so
  `pytest` ignores this folder automatically.
- A flat checklist with rotation and fall-through reads better as a script
  than as parametrised tests.

## When to run them

- Before tagging a release.
- After changing anything in a portal client, `archive/`, `facade.py` or
  `cli.py`.
- When a user reports a flake — re-run with the day's `E2E_SEED` to reproduce
  the exact court / phrase selection.

## Scheduled monitor (CI)

`.github/workflows/live-e2e.yml` runs all seven scripts daily (01:30 UTC ≈
07:00 IST), one job per backend, and:

- writes the per-check table to the job summary (Actions → run → Summary);
- uploads `<backend>.log`, `.json` and `.md` as artifacts (14 days);
- opens — or comments on — an issue labelled `live-e2e-failure` +
  `backend:<name>` when a backend has a FAIL, with the same table and the log
  tail, and auto-closes it on recovery.

Trigger it by hand from **Actions → Live E2E monitor → Run workflow**; the
optional `seed` input reproduces a past day's rotation.

### Indian egress (proxy)

Since 2026-10-22 every `*.ecourts.gov.in` host times out at TCP connect from
GitHub's hosted-runner IPs while answering normally from India (S3 is fine, so
the `archive` job never needs this). The portal-facing jobs route through an
Indian egress, resolved in this order:

| Priority | Configure | What it is |
|---|---|---|
| 1 | repository secret `E2E_PROXY_URL` = `http://user:pass@host:port` | Any HTTP CONNECT proxy with an Indian IP: a residential/ISP proxy provider with `country=IN` targeting (roughly $1–8 per GB on pay-as-you-go plans; a day's monitor is ~20–40 MB), or a tiny proxy you run on a ₹300–500/month Indian VPS. Most stable. |
| 2 | secrets `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `TS_EXIT_NODE` | A [Tailscale](https://tailscale.com/kb/1103/exit-nodes) exit node on an Indian VPS. The runner joins the tailnet via `tailscale/github-action@v4` and sets `--exit-node`; all traffic leaves from India. Free tier is enough. The OAuth client needs the `auth_keys` write scope and the `tag:ci` tag; the exit node must be approved in the admin console. |
| 3 | nothing (default) | `.github/scripts/find_india_proxy.py` pulls the public free-proxy lists for India, probes each one with an HTTPS CONNECT to `hcservices.ecourts.gov.in`, and exports the fastest responder. Free, but unreliable (2/68 answered one day, 27/73 the next; 4–16s latency) and the proxy sees the portal hostnames — fine for public court data, never for anything sensitive. Set repository variable `E2E_FREE_PROXY_FALLBACK=false` to disable. |
| 4 | — | Direct. Fails until the portals unblock GitHub's ranges. |

The resolved mode is printed as `egress:` in every report, masked in logs, and
exported as `BHARAT_COURTS_PROXY` (the SDK's own setting — see
`docs/start/configuration.md`) plus `HTTPS_PROXY` for the one check that uses
a raw httpx client. `NO_PROXY` keeps S3, GitHub and PyPI direct.

Each script has a hard `timeout-minutes` cap so a hung portal can't burn CI
minutes; the JSON summary is written at the end, so a script killed by the
cap shows "no per-check summary" and the log tail instead.
