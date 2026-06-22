# Set up bharat-courts in Claude Code

If you work in Claude Code (or Claude CoWork), this is the most reliable way to
give Claude access to Indian court data. It takes one command. After that, you
simply ask for what you need in plain English — Claude figures out which court,
which portal, and how to fetch the answer.

This page walks you through it end to end. No prior coding knowledge is assumed.

!!! info "What you're setting up"
    bharat-courts ships an **Agent Skill** — a small bundle of instructions that
    teaches Claude how to use the library. The `bharat-courts install-skills`
    command copies that bundle into a folder Claude Code already watches
    (`.claude/skills/`). Claude discovers it automatically; there is nothing else
    to switch on.

## Step 1 — Install bharat-courts

You need Python 3.11 or newer. In a terminal, install the package with the two
extras that make it most capable for legal work:

```bash
pip install "bharat-courts[ocr,archive]"
```

- `ocr` adds automatic CAPTCHA solving, so Claude can read the live eCourts
  portals (case status, orders, cause lists) without you typing in those
  squiggly codes by hand.
- `archive` adds the historical research archive — Supreme Court judgments back
  to 1950 and 25 High Courts, with no CAPTCHA and no rate limits.

!!! tip "Why both extras"
    With both installed, Claude can answer current-status questions *and*
    historical-research questions, and it picks the right source for each query
    on its own. If you only ever need one side, you can install just `[ocr]` or
    just `[archive]` — the skill works with whatever is available.

For more on the install options (including the `[all]` bundle and the ONNX
CAPTCHA solver), see the [Installation guide](../start/installation.md).

## Step 2 — Install the skill into your project

Move into the folder where you do your work — your matter folder, a research
directory, anywhere you'll be chatting with Claude Code — and run:

```bash
bharat-courts install-skills
```

You'll see exactly this confirmation:

```text
Skills installed to `.claude/skills/bharat-courts`.
```

That's it. The command copied the skill bundle into a hidden `.claude/skills/`
folder inside your current directory.

!!! note "What just happened"
    `install-skills` writes the skill files into
    `.claude/skills/bharat-courts/` relative to wherever you ran the command.
    Run it once per project folder where you want court-data access. If you
    work across several matter folders, run it in each one (or run it at the
    top level of a workspace that contains them).

## Step 3 — Just ask

Claude Code automatically discovers any skill placed under `.claude/skills/`.
Open Claude Code in that folder and ask for what you need in everyday language.
For example:

> Find all pending writ petitions for Tata Motors in the Delhi High Court from 2024.

> Pull every Supreme Court judgment authored by Justice Chandrachud between 2018 and 2024 and list the case numbers.

> What's on the cause list for the Karnataka High Court tomorrow?

> Download the latest orders in WPA 12886 of 2024 before the Calcutta High Court.

> Show me the most recent Supreme Court judgments and save the PDFs.

Claude reads the skill, decides whether the answer lives in the live portals or
the historical archive, handles the CAPTCHA and session details, and returns the
result. You stay in plain English the whole way.

For a much larger, copy-paste-ready set of example prompts grouped by task, see
[Example prompts for lawyers](prompts.md).

!!! tip "Accuracy and freshness"
    The historical archive lags live court records by about two to three months.
    If you ask about something decided very recently and Claude comes back empty
    from the archive, ask it to "check the live portal instead" — the skill knows
    to fall back, and Claude will tell you when it does.

## Claude CoWork

Claude CoWork uses the **same skill bundle**. There is no separate package and no
different file — it is the identical `.claude/skills/bharat-courts/` bundle that
`install-skills` produces.

The only difference is *how* CoWork picks the bundle up. Add it the way CoWork
loads Agent Skills, then ask in natural language exactly as you would in Claude
Code. The precise menus and steps for adding a skill are owned by Anthropic and
can change, so rather than guess at labels here, follow the official guide:

- [Anthropic Agent Skills documentation](https://docs.anthropic.com/en/docs/agents-and-tools/agent-skills/overview)

Once CoWork sees the skill, every example prompt on this page works unchanged.

!!! note "It's the same mechanism everywhere"
    Claude Code, Claude CoWork, and other Claude surfaces that support Agent
    Skills all consume the one bundle produced by `bharat-courts install-skills`.
    Install once, use anywhere Claude reads skills.

## For engineers: skip the skill if you prefer

!!! tip "You can call the library directly"
    The Agent Skill is a convenience layer over a normal Python SDK and CLI. If
    you're building tooling or scripting bulk work, you don't need Claude in the
    loop at all — call the SDK or the `bharat-courts` command yourself.

    - The [CLI guide](../guides/cli.md) covers commands like
      `bharat-courts find`, `bharat-courts hcservices search`, and
      `bharat-courts archive query`.
    - The [federated facade guide](../guides/facade.md) covers the
      `Judgments().find(...)` entry point that routes between the live portals
      and the archive for you.

## Troubleshooting

??? note "The confirmation line didn't appear"
    If you see `Skill source directory not found.` instead, the install of the
    package itself didn't complete. Re-run Step 1, then `bharat-courts
    install-skills` again.

??? note "Claude isn't using the skill"
    Make sure you ran `install-skills` *inside* the folder you have open in
    Claude Code, and that a `.claude/skills/bharat-courts/` folder now exists
    there. Skills are discovered per project directory.

??? note "CAPTCHA or live-portal questions fail"
    Confirm you installed the `ocr` extra (Step 1). Without it, the live eCourts
    portals can't be read automatically. The historical archive still works
    without `ocr`.

## Where to next

- [Example prompts for lawyers](prompts.md) — a deeper library of ready-to-use questions.
- [Installation guide](../start/installation.md) — all install options explained.
- [CLI guide](../guides/cli.md) — drive bharat-courts from the command line.
