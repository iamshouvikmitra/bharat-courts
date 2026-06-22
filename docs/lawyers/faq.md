# Frequently Asked Questions

Straight answers to the questions lawyers ask before they start using bharat-courts.
Short version: it is free, the data comes straight from official sources, and your
client's information never passes through us.

### Is it free?

Yes. bharat-courts is open-source software released under the MIT licence. There is no
subscription, no per-query fee, and no account to register for the tool itself.

The only thing you pay for is your own AI assistant subscription — for example your
Claude or ChatGPT plan — if you choose to use bharat-courts through an AI agent. That
is a payment to the AI vendor for their assistant, not to us. If you use the Python SDK
or the command line directly, there is nothing to pay at all.

!!! info "What about court fees?"
    bharat-courts only reads what the eCourts portals and the public archive already
    publish for free. It does not pay or charge any court fee.

### Where does the data come from?

Two complementary sources, both official or officially-released:

- **Live data** comes directly from the official eCourts portals —
  hcservices.ecourts.gov.in, services.ecourts.gov.in, judgments.ecourts.gov.in, the
  Supreme Court site (www.sci.gov.in), and the Calcutta High Court's own website. This
  is the same data you would see if you visited those sites yourself.
- **Historical judgments** come from the public AWS Open Data buckets maintained by
  Dattam Labs (Supreme Court from 1950 onwards, plus 25 High Courts). This archive is
  released under the CC-BY-4.0 licence.

When you reuse or republish material from the archive, attribute **Dattam Labs / the
eCourts platform** as the source.

See [About → Data sources](../about/data-sources.md) for the full breakdown.

### Can I rely on it in court?

bharat-courts fetches data *from* the official record — it does not generate or alter
case information. That makes it an excellent research and tracking aid.

That said, treat any answer an AI assistant gives you as a **research aid, not the final
word**. For anything mission-critical — a citation you will put before a judge, a
limitation date, the exact text of an order — verify it against the official record
(the certified copy, the portal itself, or the downloaded PDF) before you rely on it.
bharat-courts is software, not legal advice.

!!! warning "Verify the important things"
    AI assistants can misread or summarise loosely. For dates, citations and operative
    findings, open the actual PDF that bharat-courts downloads for you and read it.

### Is my client's data private?

Yes. Queries run **from your own machine straight to the official source**. There is no
bharat-courts server sitting in the middle, and nothing is routed through a paid data
vendor who could log or resell your searches.

The party names, case numbers and CNRs you look up go directly to the eCourts portals or
the public archive — exactly as if you typed them into the portal in your browser. If
you use an AI assistant, that assistant's vendor processes your prompt under their own
privacy terms; the court data itself still travels machine-to-source.

### How fresh is the data?

It depends on which source answers your question:

- **Live portals** reflect the **current** state — case status, today's and tomorrow's
  cause lists, recently uploaded orders. This is as fresh as the official portal.
- **The historical archive lags by roughly 2–3 months.** The Supreme Court bucket
  updates bi-monthly and the High Court buckets update quarterly.

In practice: for a matter decided in the last couple of months, or for "what is the
status right now", the live portals are the right source. For older judgments and bulk
research, the archive is faster and has no CAPTCHA.

!!! tip "If a recent judgment isn't found"
    If a search of the archive turns up nothing for a very recent year, it may simply
    not be in the archive yet. Ask your assistant to check the live portal instead.

### What is a CAPTCHA, and why might I see errors?

The live eCourts portals protect their search forms with a CAPTCHA — the distorted
characters you normally type in by hand. bharat-courts can solve these automatically:
with the optional OCR add-on installed, it reads the CAPTCHA for you and retries with a
fresh attempt if the first read is wrong (in our measurements it succeeds the large
majority of the time, with automatic retries to cover the rest).

So you will usually never see a CAPTCHA at all. Occasionally a search may fail after
several attempts, or a portal may be slow or temporarily down — in that case, simply
ask again. The historical archive has **no CAPTCHA**, so archive queries never hit this.

See [Guides → CAPTCHA handling](../guides/captcha.md) for the technical detail.

### Which courts are covered?

- The **Supreme Court of India**
- **25 High Courts** (every High Court, including bench-specific entries for Bombay and
  Allahabad)
- **700+ District Courts** across all 36 states and union territories

Plus the historical archive (Supreme Court from 1950 and 25 High Courts). For the exact
list of courts, codes and what each source can and can't do, see
[About → Data sources](../about/data-sources.md).

### Do I need to be technical?

No — not for everyday use. If you use Claude with the bharat-courts skill installed, you
simply ask questions in plain English and the assistant does the rest. There is a small
one-time setup to get it running.

- Setting it up with Claude (no coding): [For lawyers → Claude Desktop](claude-desktop.md)
  and [Claude Code](claude-code.md).
- Using other AI tools: [ChatGPT and others](chatgpt-and-others.md).
- Ready-to-paste example questions: [Prompts that work](prompts.md).

If you are (or have) an engineer, the [Installation](../start/installation.md) and
[Quickstart](../start/quickstart.md) pages cover the Python SDK and command line.

### What can't it do yet?

We would rather be honest than oversell. Current limitations:

- **Full-text "find any case mentioning X" searches use the live judgments portal**,
  which is CAPTCHA-gated and rate-limited, so they are slower than structured searches
  against the archive. Use specific filters (court, year, judge) where you can.
- **Supreme Court live access is a recent-judgments feed only.** bharat-courts can pull
  the Supreme Court's latest published judgments and download those PDFs, but search by
  case number or party name on the SCI site is not wired up yet. For historical SCI
  judgments, use the archive instead.
- **Some order PDFs may simply not be uploaded by the court.** When that happens
  bharat-courts can still show you that the order exists, but the download will fail
  because the court never published the file.
- **Live case status is limited to what the search results return.** Fields like next
  hearing date, sitting judges and disposal status live behind a separate case-history
  page that the tool does not yet read, so they may come back blank.

### Where do I start?

- New to AI assistants: [For lawyers — overview](index.md).
- Want examples to copy: [Prompts that work](prompts.md).
- Building on top of it: [Quickstart](../start/quickstart.md).
