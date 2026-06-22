# Configuration

bharat-courts reads its settings from a single configuration object,
`BharatCourtsConfig`, defined in `src/bharat_courts/config.py`. It is built on
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/),
which means every field can be overridden from an **environment variable** or a
**`.env` file** — no code changes required.

All variables share the prefix `BHARAT_COURTS_`. So the field `timeout` is set
with the environment variable `BHARAT_COURTS_TIMEOUT`.

!!! info "The defaults are sensible"
    You do not need to configure anything to get started. The values below are
    only worth changing if you are scraping unusually wide queries, running
    behind a proxy, or want quieter (or louder) logging.

## Settings reference

These are the only settings on `BharatCourtsConfig`. Each one is a plain Python
attribute with a default; the matching environment variable is the prefix plus
the upper-cased field name.

| Setting | Env var | Default | What it does |
|---|---|---|---|
| `request_delay` | `BHARAT_COURTS_REQUEST_DELAY` | `1.0` | Seconds to wait between requests to a court portal. Polite rate limiting so the SDK does not hammer the eCourts servers. |
| `user_agent` | `BHARAT_COURTS_USER_AGENT` | a Chrome-on-macOS string | The `User-Agent` header sent with every request. The portals expect a browser-like agent; override only if you have a specific reason. |
| `timeout` | `BHARAT_COURTS_TIMEOUT` | `60` | HTTP request timeout, in seconds. Wide District Court party-name searches genuinely take 30–60s on the portal, so the default is deliberately generous. |
| `max_retries` | `BHARAT_COURTS_MAX_RETRIES` | `3` | How many times a failed HTTP request is retried before giving up. |
| `log_level` | `BHARAT_COURTS_LOG_LEVEL` | `"INFO"` | Logging verbosity (`"DEBUG"`, `"INFO"`, `"WARNING"`, `"ERROR"`). Routing decisions in the `Judgments` facade are logged at `INFO`. |

!!! note "These settings drive the live portal clients"
    `request_delay`, `timeout`, and `max_retries` apply to the rate-limited
    HTTP client used by the live eCourts clients (`HCServicesClient`,
    `DistrictCourtClient`, `JudgmentSearchClient`, and friends). The archive
    backend talks to plain S3 and does not need rate limiting, so it is not
    governed by `request_delay`.

## Setting values

### Option 1 — environment variables

Export the variables in your shell before running your script or the CLI:

```bash
export BHARAT_COURTS_TIMEOUT=120
export BHARAT_COURTS_REQUEST_DELAY=2.0
export BHARAT_COURTS_LOG_LEVEL=DEBUG

python my_search.py
```

This is the right approach for CI pipelines, containers, and one-off runs.

### Option 2 — a `.env` file

pydantic-settings automatically loads a file named `.env` from the current
working directory. Create one next to your script:

```text
BHARAT_COURTS_TIMEOUT=120
BHARAT_COURTS_REQUEST_DELAY=2.0
BHARAT_COURTS_LOG_LEVEL=DEBUG
```

No extra code is needed — when `bharat_courts` is imported, the config object
picks the file up.

!!! tip "Keep `.env` out of version control"
    A `.env` file is convenient for local development, but add it to your
    `.gitignore` so machine-specific settings (and anything sensitive you add
    later) do not get committed.

## How the config is loaded

The module exposes a single, module-level config object that is constructed
**once**, at import time:

```python
# bharat_courts/config.py
config = BharatCourtsConfig()
```

Every live client falls back to this shared `config` singleton when you do not
pass one explicitly. If you want per-client settings, build your own instance
and hand it in:

```python
import asyncio
from bharat_courts import HCServicesClient
from bharat_courts.config import BharatCourtsConfig

async def main():
    cfg = BharatCourtsConfig(timeout=120, request_delay=2.0)
    async with HCServicesClient(config=cfg) as client:
        ...

asyncio.run(main())
```

!!! warning "Because the singleton is built at import time, set env vars first"
    The `config` object reads the environment when `bharat_courts` is first
    imported. Set your environment variables (or write your `.env` file)
    **before** importing the package, otherwise the change will not be picked
    up for the default singleton. Passing an explicit `BharatCourtsConfig(...)`
    to a client always works regardless of import order.

!!! warning "`0` is a legal value — do not collapse it with `or`"
    When you read a numeric setting in your own code, do not write
    `value = arg or DEFAULT`. In Python, `bool(0)` is `False`, so `0 or DEFAULT`
    silently becomes `DEFAULT` — turning a deliberate `0` (e.g. "no delay")
    into the default. Use an explicit `None` check instead:

    ```python
    value = arg if arg is not None else DEFAULT
    ```

    This bit the SDK once with a `ttl_seconds=0` argument; it is worth keeping
    in mind whenever a `0` is meaningful.

## Archive cache settings

The opt-in [archive backend](../guides/archive.md) caches downloaded parquet
metadata and judgment PDFs under `~/.cache/bharat-courts/archive/`. These cache
controls are **not** part of `BharatCourtsConfig` — they are read directly by
the archive module — but they are still environment variables, so they belong
in the same `.env` file:

| Env var | Default | What it does |
|---|---|---|
| `BHARAT_COURTS_ARCHIVE_CACHE_MAX_GB` | `5` | Maximum size of the on-disk archive cache, in GiB. The cache uses LRU eviction once it exceeds this cap. |
| `BHARAT_COURTS_ARCHIVE_METADATA_TTL_DAYS` | `30` | How long mirrored parquet metadata shards are considered fresh before they are re-fetched from S3. |

You can also set the cache directory and size limit directly when constructing
an `ArchiveClient` via its `cache_dir` and `cache_max_bytes` arguments — see the
[archive guide](../guides/archive.md).

## See also

- [Installation](installation.md) — extras (`[ocr]`, `[archive]`, `[cli]`, `[all]`) and Python version.
- [Quickstart](quickstart.md) — your first search in a few lines.
- [Config API reference](../reference/config.md) — the auto-generated `BharatCourtsConfig` class reference.
