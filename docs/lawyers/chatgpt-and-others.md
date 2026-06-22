# Using bharat-courts with ChatGPT and Other AI Assistants

You may already be working with ChatGPT, Gemini, Copilot, or another assistant
and wonder whether bharat-courts can sit alongside them the way it does with
Claude. The honest answer: yes, but the experience is different, and it pays to
know exactly what works where before you start.

This page is candid about the trade-offs. The smoothest, no-setup-in-the-chat
experience today is with Claude. Everywhere else, the realistic, working path is
to use bharat-courts as a **tool** — through its command line or its Python
library — and hand the results to your assistant.

!!! info "What works where, at a glance"

    | Assistant | How it connects to bharat-courts | Setup effort |
    |---|---|---|
    | **Claude Code** (terminal) | Bundled Agent Skill — ask in plain English | One command |
    | **Claude Desktop / Claude.ai** | Agent Skill | A few clicks |
    | **ChatGPT, Gemini, Copilot, others** | Run the CLI or Python yourself, feed the output to the chat | Manual, but reliable |
    | Any tool that can run local scripts | Wire the CLI/Python in as a custom tool | Depends on the tool |

    There is **no official ChatGPT plugin** and **no MCP server** for
    bharat-courts. The plain-English "skill" mechanism is built for Claude. We
    would rather tell you that plainly than have you hunt for an integration
    that does not exist.

## Why Claude is the easy path (and the others are not)

bharat-courts ships an **Agent Skill** — a small instruction file the SDK can
install into Claude with one command:

```bash
bharat-courts install-skills
```

That file teaches Claude how to call the library, handle CAPTCHAs, and pick the
right data source. Once installed, you ask questions in ordinary English and
Claude does the work. See [Claude Code](claude-code.md) and
[Claude Desktop](claude-desktop.md) for the full walkthroughs.

Skills are a Claude feature. ChatGPT, Gemini, and other assistants do not read
that skill file, so the same "just ask" experience is not available there yet.
That does not mean they are shut out — it means you connect them a different
way.

## The honest, working pattern for ChatGPT and others

bharat-courts is plain Python plus a command-line tool that prints **clean
JSON**. Any assistant that can either run code or accept pasted data can use it.
There are two practical shapes:

1. **Run a command, paste the result into the chat.** Works with every
   assistant, no integration needed.
2. **Let the assistant run the code.** Works where the assistant has a code
   sandbox or can call a local tool you define.

### Pattern 1 — run the CLI, feed the JSON to your assistant

Every CLI command accepts a global `--json` flag and prints structured JSON to
standard output. You run the command in your terminal, then paste the JSON into
ChatGPT (or any chat) and ask it to summarise, compare, or draft from it.

Find a judgment across the archive and the live portals:

```bash
bharat-courts find --text "right to privacy" --json
```

Search a High Court by party name (note: the registration year is mandatory):

```bash
bharat-courts hcservices search-by-party delhi --party "state" --year 2024 --json
```

Query the historical archive by judge and year range (no CAPTCHA, no rate
limits):

```bash
bharat-courts archive query --court sci --judge "chandrachud" --year 2018-2024 --json
```

Each prints a JSON array you can paste straight into your chat. A typical
exchange:

```text
You:   Here is JSON from a court-data tool. Summarise these judgments in a
       table — case title, court, decision date, outcome — and flag any that
       look like they involve a public-sector bank.

       [paste the JSON output here]

ChatGPT: <reads the structured data and answers>
```

Because the output is real data the library fetched, the assistant is
summarising facts you pulled, not guessing. That is the key benefit of this
route — you keep the AI well away from inventing case details.

!!! tip "Save the output to a file for longer results"

    Wide party-name searches can return many records. Redirect the JSON to a
    file and either upload it to your assistant or open it beside the chat:

    ```bash
    bharat-courts find --judge "nariman" --court sci --year 2019 --json > results.json
    ```

    ChatGPT, Gemini, and similar tools can all read an uploaded `.json` file.

If you are new to the command line, the full command list, flags, and download
options live in the [CLI guide](../guides/cli.md).

### Pattern 2 — let the assistant run the code

If your assistant has a code-execution sandbox (for example, ChatGPT's data
analysis / code interpreter) **and** that sandbox has internet access and the
package installed, it can run bharat-courts directly. The library is ordinary
async Python:

```python
import asyncio
from bharat_courts import Judgments

async def main():
    async with Judgments() as j:
        results = await j.find(judge="chandrachud", year=(2018, 2024),
                               court="sci", limit=10)
        for r in results:
            print(r.decision_date, r.case_id, r.title)

asyncio.run(main())
```

!!! warning "Sandbox limits are real"

    Many hosted code sandboxes have **no outbound internet access**. The live
    eCourts portals and the AWS archive both require network calls, so a locked
    sandbox cannot reach them. When that is the case, fall back to Pattern 1:
    run the command on your own machine and paste the JSON in. Treat Pattern 2
    as a bonus where it happens to work, not a guarantee.

### Pattern 3 — wire it in as a custom tool (for builders)

If you are building an agent or a function-calling setup — or your assistant
supports running local scripts or custom tools — you can register bharat-courts
as one of its tools. The natural wrapper is the federated `find` entry point:

```python
import asyncio
from bharat_courts import Judgments

async def find_indian_judgments(text=None, judge=None, court=None,
                                year=None, cnr=None, limit=10):
    """Tool: find Indian court judgments (archive + live eCourts)."""
    async with Judgments() as j:
        results = await j.find(text=text, judge=judge, court=court,
                               year=year, cnr=cnr, limit=limit)
        return [r.to_dict(exclude_none=True) for r in results]
```

Expose that function to your framework's tool/function-calling interface and the
model can call it with structured arguments. Every result is a dataclass with
`to_dict()` and `to_json()`, so it serialises cleanly into a tool response.

!!! info "\"Any MCP-compatible assistant\" — read this carefully"

    bharat-courts does **not** ship an MCP server. But MCP, and similar
    local-tool mechanisms, exist precisely so you can wrap a script as a tool
    your assistant calls. If your assistant supports running local tools, you
    can wire bharat-courts in yourself using the function pattern above. We are
    describing a path you can build, not a shipped, supported integration.

## A note on accuracy, cost, and privacy

These hold regardless of which assistant you use:

- **The data is real.** bharat-courts fetches from the official eCourts portals
  and the public AWS Open Data archive. When you feed its JSON to an assistant,
  the assistant is working from fetched records, not its training memory — which
  is exactly what you want for anything case-specific.
- **No bharat-courts subscription or API key.** The library is free and
  open-source. The archive needs no account at all. You may still pay your AI
  provider (for example, ChatGPT) separately for their service.
- **You control where data goes.** With Pattern 1 you decide what to paste into
  the chat. Sensitive matter details never leave your machine unless you choose
  to share them.

## Which route should I pick?

- **You want the least friction and plain-English questions** → use
  [Claude Code](claude-code.md) or [Claude Desktop](claude-desktop.md).
- **You are committed to ChatGPT or another assistant** → run the
  [CLI](../guides/cli.md) with `--json` and paste the results in (Pattern 1).
  This is the most reliable route everywhere.
- **You are building software around an assistant** → wrap
  `Judgments().find(...)` as a tool (Pattern 3) and start from the
  [Quickstart](../start/quickstart.md).

Whichever you choose, the engine underneath is the same: one library covering
25+ High Courts, 700+ District Courts, the Supreme Court, and a historical
archive going back to 1950.
