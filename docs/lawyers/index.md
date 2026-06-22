# bharat-courts for Lawyers

**bharat-courts gives the AI assistant you already use — Claude, and other tools — live and historical access to the official Indian court record.** Instead of logging into clunky eCourts portals, solving CAPTCHAs by hand, and copy-pasting case details one row at a time, you simply ask in plain English: *"What's the next hearing in my Bombay High Court writ petition?"* or *"Find me Supreme Court judgments on the right to privacy."* The assistant reaches straight into the eCourts platform and the public judgment archive, does the tedious clicking for you, and hands back the answer.

It is free, open-source, and runs on your own machine. There is no new subscription, no third-party legal database to pay for, and your queries stay on your computer.

!!! info "Who this section is for"
    These pages are written for practising lawyers and their teams — no coding required. If you build legal-tech and want the Python SDK and API signatures, head to the [engineer guides](../guides/facade.md) and the [API reference](../reference/index.md) instead.

## What it can do for you

Think of it as a research clerk that never sleeps and never loses a session to a CAPTCHA.

### Track your matters and check case status

Look up any case by case number, party name, or advocate across **25+ High Courts**, **700+ District Courts**, and the Supreme Court. Pull up the parties, the CNR number, the case type, and the filing details in seconds.

> *"Find all matters for Reliance Industries in the Delhi High Court filed in 2024."*

> *"Look up writ petition W.P.(C) 4520 of 2023 in the Bombay High Court."*

!!! note "An honest note on live status"
    The eCourts case-search endpoint the tool reads returns the parties, case number and CNR, but **not** a live "Pending / Disposed" flag or the next-hearing date — those sit behind a separate case-history page the library does not yet read. For the most reliable picture of where a matter stands today, treat the tool as your fast first look and confirm the live status detail on the portal.

### See the daily cause lists

Find out which cases are listed before which bench, on any given day, without refreshing the portal all morning.

> *"Download the civil cause list for the Delhi High Court for tomorrow."*

> *"What's listed before the District & Sessions Judge at Patna Sadar on 20 March?"*

### Pull order and judgment PDFs

Get the PDFs of orders and judgments in a matter with a single request — saved straight to a file you can read or forward.

> *"Download every order in this Calcutta High Court WPA from 2024."*

> *"Get me the latest order PDF in this case and summarise it."*

### Search 75 years of judgments and precedent

Behind the live portals sits a historical archive of **Supreme Court judgments from 1950 onwards and 25 High Courts** — a public, openly-licensed dataset (CC-BY-4.0) hosted on AWS Open Data. It carries no CAPTCHA and no rate limits, so precedent research is fast.

> *"Find judgments authored by Justice Chandrachud in the Supreme Court between 2018 and 2024."*

> *"Show me all Delhi High Court judgments from 2020 mentioning Tata."*

!!! tip "One question, the right source"
    You never have to decide whether your question needs the live portal or the historical archive. The library's `find` routing picks the right backend for you — a CNR or a precedent search goes to the fast archive; a free-text body search goes to the live portal — and tells you which source each result came from.

## Why it's different

!!! info "Free and open-source"
    bharat-courts is released under the MIT licence. There is no per-seat fee, no usage cap, and no expensive commercial database in the middle. You pay nothing to use it.

!!! info "Runs locally — your work stays confidential"
    The tool runs on your own computer. Your searches — client names, case numbers, the matters you are researching — are sent only to the official court systems they query, not to any bharat-courts server. There isn't one.

!!! info "Straight from the official source"
    Results come directly from the eCourts platform (`hcservices.ecourts.gov.in`, `services.ecourts.gov.in`, `judgments.ecourts.gov.in`), the Supreme Court's own site, the Calcutta High Court website, and the government-affiliated AWS Open Data judgment archive. You are reading the court record, not a re-keyed third-party copy.

!!! warning "Where it is honest about its limits"
    The historical archive lags real time by roughly **2–3 months** (it refreshes bi-monthly for the Supreme Court and quarterly for the High Courts), so a judgment delivered last week may only be reachable via the live portal. Automated CAPTCHA solving is good but not perfect, so the occasional live lookup needs a retry — the library handles those retries for you. When something is unavailable or stale, the assistant should say so rather than guess.

## Get set up in minutes

Pick the assistant you already use. Each guide walks you through installation and your first query in plain English.

<div class="grid cards" markdown>

-   :material-monitor:{ .lg .middle } __[Use it in Claude Desktop](claude-desktop.md)__

    ---

    The simplest path for most lawyers. Install the app, add the bharat-courts
    skill, and ask away — no terminal required for day-to-day use.

-   :material-console:{ .lg .middle } __[Use it in Claude Code](claude-code.md)__

    ---

    For the command line. Run `bharat-courts install-skills` once and Claude Code
    can look up cases and judgments for you in any project.

-   :material-robot-outline:{ .lg .middle } __[ChatGPT and other assistants](chatgpt-and-others.md)__

    ---

    Not on Claude? You can still use bharat-courts as a tool the honest way —
    through its Python command-line interface. Here's how.

-   :material-comment-text-multiple:{ .lg .middle } __[Example prompts to copy](prompts.md)__

    ---

    A ready-to-use library of plain-English prompts for case status, cause lists,
    order PDFs, and precedent research — grouped by what you need.

</div>

## Next step

Most lawyers should start with **[Claude Desktop](claude-desktop.md)** — it's the gentlest setup. Once it's connected, open the **[example prompts](prompts.md)** and try one against a matter you're working on today. If you hit a snag or want to know more about accuracy, cost, and privacy, the **[FAQ](faq.md)** answers the questions lawyers ask most.
