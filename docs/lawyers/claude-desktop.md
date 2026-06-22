# Set up bharat-courts in Claude Desktop

This page walks you through giving Claude Desktop the ability to look up Indian
court data for you — case status, orders, cause lists, and judgments going back
to 1950 — so you can ask in plain English and get real answers pulled from the
official eCourts portals and the public judgment archive.

You do not need to be a programmer. There are four short steps. Set it up once
and it keeps working.

!!! info "What you are actually installing"
    bharat-courts ships an **Agent Skill** — a small folder of instructions that
    teaches Claude how and when to use the tool. There is no separate plugin,
    no account to create, and no API key. Claude runs the bharat-courts
    software on your own computer when you ask it a court-data question.

---

## Step 1 — Install Python and the package

Claude Desktop needs the bharat-courts software present on your computer so it
can actually run searches. This is a one-time install.

!!! note "Prerequisite: Python 3.11 or newer"
    bharat-courts requires **Python 3.11+**. If you do not already have it,
    download it from [python.org](https://www.python.org/downloads/) and run the
    installer. On the first screen of the Windows installer, tick
    **"Add Python to PATH"** before clicking Install.

Once Python is installed, open a terminal (Terminal on macOS, Command Prompt or
PowerShell on Windows) and run:

```bash
pip install "bharat-courts[ocr,archive]"
```

The two extras in the brackets are what make the assistant genuinely useful:

| Extra | What it adds | Why it matters to you |
|---|---|---|
| `ocr` | Automatic CAPTCHA solving (the `ddddocr` engine) | The live eCourts portals are CAPTCHA-gated. With this, Claude solves them for you — no typing in squiggly letters by hand. |
| `archive` | Historical archive support (DuckDB over the public AWS Open Data buckets) | Lets Claude search Supreme Court judgments from 1950 onward and 25 High Courts instantly, with no CAPTCHA and no rate limits. |

Installing both gives Claude access to **live** court data (current status,
cause lists, in-progress orders) *and* the **historical archive** (past
judgments, bulk research). That is the recommended setup.

!!! tip "If the command is not found"
    On some systems the command is `pip3` instead of `pip`, or
    `python3 -m pip install "bharat-courts[ocr,archive]"`. If none work, Python
    was likely not added to PATH during install — re-run the Python installer
    and make sure that box is ticked.

---

## Step 2 — Generate the skill folder

bharat-courts can write its skill folder for you. In the same terminal, navigate
to a folder you can find again (your home folder is fine) and run:

```bash
bharat-courts install-skills
```

This copies the skill into a folder named:

```text
.claude/skills/bharat-courts/
```

(created inside whatever directory you ran the command from). The command prints
the exact location it wrote to — note it down, you will point Claude Desktop at
this folder in the next step.

??? note "Prefer to use the folder shipped inside the package?"
    The skill also lives inside the installed package itself, at
    `bharat_courts/skill/` within your Python environment. Running
    `install-skills` is the simplest way to get a clean, easy-to-find copy, so
    we recommend that over hunting for the bundled folder.

---

## Step 3 — Add the skill in Claude Desktop

Claude Desktop loads Agent Skills from its settings. Because Anthropic refines
the Desktop interface from time to time, we will describe this in general terms
rather than naming exact buttons that may change.

1. Open **Claude Desktop** and go into its **Settings**.
2. Find the area for **Skills** (sometimes presented under Capabilities).
3. **Add** a skill and point it at the `bharat-courts` skill folder you created
   in Step 2 (the `.claude/skills/bharat-courts/` folder).
4. Make sure the skill is **enabled**.

!!! info "Follow Anthropic's current instructions for the exact clicks"
    The precise menu names and the location of the Skills setting can change
    between Claude Desktop versions. For the up-to-date, step-by-step
    walkthrough straight from the vendor, see Anthropic's official Agent Skills
    documentation at [docs.anthropic.com](https://docs.anthropic.com) and the
    help centre at [support.anthropic.com](https://support.anthropic.com).

---

## Step 4 — Verify it works

Start a new chat in Claude Desktop and ask a simple question, for example:

> "Using bharat-courts, list the most recent Supreme Court judgments."

If everything is wired up, Claude will recognise the bharat-courts skill, run it,
and come back with real results rather than saying it cannot access court data.

!!! tip "A good first test"
    The recent Supreme Court feed is the easiest thing to verify because it
    needs no CAPTCHA and no case details — just a clean check that the skill is
    connected. Once that works, move on to the things you actually need every
    day.

For dozens of ready-to-paste, plain-English prompts — finding a client's pending
matters, pulling orders, checking tomorrow's cause list, researching past
judgments — see the [example prompts page](prompts.md).

---

## Troubleshooting

??? question "Claude says it cannot find the tool, or the skill does nothing"
    The most common cause is that bharat-courts is installed in a *different*
    Python environment from the one Claude Desktop uses. Make sure you ran the
    `pip install "bharat-courts[ocr,archive]"` command in the same Python that
    is on your system PATH. Re-running that install command and then restarting
    Claude Desktop usually resolves it. Also confirm the skill is enabled in
    Settings and that you pointed it at the `.claude/skills/bharat-courts/`
    folder (not its parent).

??? question "I see CAPTCHA errors when Claude searches the live portals"
    The live eCourts portals are protected by CAPTCHAs. Automatic solving comes
    from the `ocr` extra — if you installed plain `bharat-courts` without it,
    re-run:

    ```bash
    pip install "bharat-courts[ocr]"
    ```

    CAPTCHA solving is automatic but not perfect; the tool retries with fresh
    attempts, so an occasional miss is normal and usually clears on a retry.

??? question "Historical / older judgment searches return nothing"
    Make sure the `archive` extra is installed (`pip install "bharat-courts[archive]"`).
    Also note the archive lags real time by a couple of months — for a judgment
    delivered in the last 2–3 months, ask Claude to check the **live** portal
    instead.

---

## Prefer Claude Code?

If you work in a terminal or a code editor, the setup is even quicker and uses
the same skill folder. See [Set up in Claude Code](claude-code.md).

For the full installation reference, including every available extra, see
[Installation](../start/installation.md).
