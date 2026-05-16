# Integration tests

Live end-to-end tests that hit real external services (eCourts portals, AWS
Open Data buckets). **Not run by default** — they're slow, require network,
and depend on third-party portals that can change shape underneath us.

| File | Hits | Runtime | Purpose |
|---|---|---|---|
| `hcservices.py` | `hcservices.ecourts.gov.in` | ~60s (CAPTCHA-dependent) | Bench listing, case types, cause list, case status, OCR solver stress |
| `districtcourts.py` | `services.ecourts.gov.in` | ~30s | Bihar drill-down + party-name search |
| `archive.py` | S3: `indian-{supreme,high}-court-judgments` | ~30-45s cold (~5s warm) | Archive metadata, parquet cache, CNR routing, streaming, PDF fetch, federated facade |
| `calcuttahc_wpa_12886.py` | `hcservices.ecourts.gov.in` + `judgments.ecourts.gov.in` | ~30s | Regression for a known-good Calcutta HC case |

## Running

These are standalone scripts, not pytest tests. Invoke directly:

```bash
source .venv/bin/activate

# Archive + facade (covers everything added in 0.3.0)
python tests/integration/archive.py

# Live eCourts portals
python tests/integration/hcservices.py
python tests/integration/districtcourts.py
python tests/integration/calcuttahc_wpa_12886.py
```

Each script prints a PASS/FAIL line per check and exits non-zero if any
check fails — fine for use in pre-release validation or a manually
triggered CI job.

## Why not pytest?

- They hit external services, so unreliable as a default test gate.
- Pytest's default discovery pattern (`test_*.py`) doesn't match these
  filenames, so `pytest` ignores this folder automatically.
- The scripts use a plain `TestResult` class + standalone `asyncio.run`
  so they read like a checklist rather than a test suite.

## When to run them

- Before tagging a release.
- After changing anything in `bharat_courts/archive/`,
  `bharat_courts/facade.py`, or a portal client.
- When a user reports a flake — re-run to reproduce against current
  portal state.
