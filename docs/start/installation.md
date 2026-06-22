# Installation

`bharat-courts` is a regular Python package — install it with `pip` from PyPI. The base
package is small (an async HTTP stack and a few parsers); the heavier capabilities (CAPTCHA
solving, the historical archive) are opt-in **extras** so you only install what you need.

## Requirements

- **Python 3.11 or newer** (3.11 and 3.12 are tested and supported).
- A working `pip`. If your system Python is older than 3.11, install `python3.12` and run
  `python3.12 -m pip ...` in the commands below.

!!! tip "Use a virtual environment"
    Keep the install isolated from your system Python:

    ```bash
    python3.12 -m venv .venv
    source .venv/bin/activate    # Windows: .venv\Scripts\activate
    pip install bharat-courts
    ```

## Base install

```bash
pip install bharat-courts
```

This gives you the SDK and every client class — `Judgments`, `HCServicesClient`,
`DistrictCourtClient`, `JudgmentSearchClient`, `SCIClient`, `CalcuttaHCClient`, and
`ArchiveClient` — plus the court registry and data models. It pulls in `httpx`,
`pydantic-settings`, `beautifulsoup4`, and `lxml`.

What the base install does **not** include: automatic CAPTCHA solving, the historical
archive (DuckDB), and the command-line tool. Each is an extra, described below.

## Optional extras

Extras are added in square brackets after the package name. You can combine them with commas,
e.g. `pip install "bharat-courts[ocr,archive]"`.

| Extra | Command | What it enables |
|---|---|---|
| `ocr` | `pip install "bharat-courts[ocr]"` | Automatic CAPTCHA solving via `ddddocr` (+ `Pillow`). **Recommended** for the live eCourts portals. |
| `archive` | `pip install "bharat-courts[archive]"` | The historical archive (`ArchiveClient`) — DuckDB queries against the public AWS Open Data buckets. |
| `onnx` | `pip install "bharat-courts[onnx]"` | An alternative ONNX-based CAPTCHA solver (`onnxruntime` + `numpy` + `Pillow`). Needs `HF_TOKEN` — see the note below. |
| `cli` | `pip install "bharat-courts[cli]"` | The `bharat-courts` command-line tool (`click` + `rich`). |
| `all` | `pip install "bharat-courts[all]"` | Everything above plus the dev/test tooling (`pytest`, `respx`, `ruff`). |

!!! info "Why CAPTCHA solving is an extra"
    The official eCourts portals gate searches behind image CAPTCHAs. The live clients
    (`HCServicesClient`, `DistrictCourtClient`, `JudgmentSearchClient`, `CalcuttaHCClient`)
    need a CAPTCHA solver to run unattended. Install `[ocr]` and the clients auto-detect and
    use `ddddocr` with no extra configuration. The archive (`ArchiveClient`) and the Supreme
    Court feed (`SCIClient`) are CAPTCHA-free and work on the base install.

## Recommended: `[ocr,archive]`

For most users — and especially anyone using the `Judgments` facade — install both the OCR and
archive extras:

=== "pip"

    ```bash
    pip install "bharat-courts[ocr,archive]"
    ```

=== "uv"

    ```bash
    uv pip install "bharat-courts[ocr,archive]"
    ```

The [`Judgments` facade](../guides/facade.md) is the recommended entry point for "find a
judgment matching X". It owns both backends and routes each query to the right one:

- **structured filters** (judge, party, year, court, citation) and **CNR lookups** go to the
  **archive** — fast, no CAPTCHA, no rate limits. This needs `[archive]`.
- **free-text** searches go to the **live** judgments portal, which is the only backend that
  does full-body text search. This needs a CAPTCHA solver, i.e. `[ocr]`.

Install only one extra and the facade still works, but it can only use the backend you have.
Installing both lets it pick the best route for every query.

## The ONNX CAPTCHA solver

`[onnx]` provides `ONNXCaptchaSolver`, a lighter alternative to `ddddocr`. Most users should
prefer `[ocr]`; reach for ONNX only if you have a specific reason.

!!! note "ONNX requires a Hugging Face token"
    The ONNX model is hosted on Hugging Face and download requires authentication. Set the
    `HF_TOKEN` environment variable before using `ONNXCaptchaSolver`:

    ```bash
    export HF_TOKEN=hf_...        # get a token at https://huggingface.co/settings/tokens
    ```

    Without a valid `HF_TOKEN` the model download fails. If you just want auto-solving that
    works out of the box, use `[ocr]` instead — it has no auth requirement.

See [CAPTCHA handling](../guides/captcha.md) for how to choose and configure a solver, including
the manual (stdin) solver and writing your own.

## The command-line tool

Installing `[cli]` (or `[all]`) registers the `bharat-courts` command, backed by `click` and
`rich`. Verify it:

```bash
bharat-courts --help
```

See the [CLI guide](../guides/cli.md) for the available commands.

## Installing the AI-agent skill

`bharat-courts` ships a Claude **Agent Skill** so you can ask your AI assistant for court data
in plain English instead of writing code. Once the package is installed (with `[cli]` or
`[all]`), copy the skill into your project:

```bash
bharat-courts install-skills
```

This writes the skill into `.claude/skills/bharat-courts/`, after which Claude can use the SDK
on your behalf. For a non-technical, step-by-step setup, see the lawyer-facing guides:

- [Using bharat-courts in Claude Desktop](../lawyers/claude-desktop.md)
- [Using bharat-courts in Claude Code](../lawyers/claude-code.md)
- [ChatGPT and other assistants](../lawyers/chatgpt-and-others.md)

!!! note "Claude-native skill"
    The skill is a Claude Agent Skill (a `SKILL.md` definition). There is no MCP server and no
    ChatGPT plugin. For non-Claude tools, the honest path is to use the Python SDK or CLI as a
    tool the assistant can call.

## Verify your install

A quick check that the package imports and the registry loads:

```python
import asyncio
from bharat_courts import Judgments, get_court

async def main():
    print(get_court("delhi"))          # Court(name="Delhi High Court", ...)
    async with Judgments() as j:
        results = await j.find(cnr="DLHC010230802020")
        print(f"{len(results)} result(s)")

asyncio.run(main())
```

If that runs, you're ready to go.

## Next steps

- [Quickstart](quickstart.md) — your first real searches and PDF downloads.
- [Configuration](configuration.md) — cache locations, rate limits, and environment variables.
- [The `Judgments` facade](../guides/facade.md) — the recommended way to find judgments.
