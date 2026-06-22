# What You Can Ask

This is your prompt playbook. Once bharat-courts is installed into your AI assistant
(see [Claude Desktop](claude-desktop.md) or [Claude Code](claude-code.md)), you can ask
for Indian court data in plain English — no case-citation format to memorise, no portal
to navigate, no CAPTCHAs to squint at.

Below are the everyday tasks lawyers do most, each with example prompts you can copy,
adapt, and type straight into the chat. A short note under each group tells you what
comes back.

!!! tip "How to read this page"
    The prompts are written the way a real person would type them. You do not need exact
    case numbers or codes — the assistant figures out the right court and the right lookup
    from what you describe. The more specific you are (court, year, party name), the
    faster and tighter the answer.

---

## 1. Case status and next hearing

Find a matter and see where it stands — across the High Courts and the 700+ District
Courts on the eCourts platform. You can search by **party name**, by **case number**, or
by **CNR** (the 16-character Case Number Record that uniquely identifies every case).

```text
Find all cases for Reliance Industries in the Delhi High Court filed in 2024.
```

```text
Look up W.P.(C) 4520 of 2023 in the Bombay High Court and show me the case details.
```

```text
What's the CNR and the parties for case number 100 of 2024 in the Patna district court, Patna Sadar?
```

```text
Pull up the case with CNR DLHC010230802020.
```

```text
Search for matters where State of Bihar is a party in the Patna District Court in 2024.
```

**What comes back:** the matched cases with case number, case type (e.g. "W.P.(C)"),
the petitioner and respondent, the court name, and the CNR. You can then ask follow-ups
like "now get me the orders in that one" (see section 3).

!!! note "A note on live status fields"
    The eCourts case-lookup returns the parties, case number, and CNR reliably. Fields
    like the current Pending/Disposed status, the next hearing date, and the judges are
    *not* part of that quick lookup — they sit behind a separate case-history page the
    tool does not read yet. For the authoritative current status of a live matter, treat
    the result as a starting point and confirm on the official portal or the case file.

For the engineering detail behind these lookups, see the
[High Courts guide](../guides/high-courts.md) and the
[District Courts guide](../guides/district-courts.md).

---

## 2. The daily cause list

See which cases are listed before which bench, for today or any date you name — for
both High Courts and District Courts.

```text
What's on the civil cause list for the Delhi High Court tomorrow?
```

```text
Get me the criminal cause list for the Karnataka High Court for 15 January 2025.
```

```text
Download the cause list PDF for the Principal Bench of the Bombay High Court today.
```

```text
Show me the District & Sessions Court cause list for Patna Sadar for 20 March 2026.
```

**What comes back:** for High Courts, the list of benches sitting that day with a
downloadable cause-list PDF per bench. For District Courts, structured entries —
serial number, case number, parties, advocates, and the court number — for the date and
court you asked about.

!!! info "Dates"
    If you don't name a date, you get today's list. Dates are interpreted as
    DD-MM-YYYY internally, but you can just say "tomorrow" or "15 January 2025" and the
    assistant will translate.

---

## 3. Orders and judgments in a specific case

List every order passed in a case — and download the PDFs.

```text
List all the orders in W.P.(C) 4520 of 2023 before the Bombay High Court and download each PDF.
```

```text
Get me the latest order in case number 1 of 2024 in the Delhi High Court.
```

```text
Find the orders in WPA 12886 of 2024 in the Calcutta High Court (appellate side) and save the judgments.
```

```text
Download all judgments in case number 100 of 2024 from the Patna district court.
```

**What comes back:** each order with its date, type ("Order", "Interim Order",
"Judgment"), the judge, and a link to the PDF — which the assistant can download and save
to a file for you.

!!! tip "Calcutta High Court has its own door"
    For Calcutta HC matters from September 2020 onwards, the tool can search the court's
    own website directly, which often has better PDF coverage and includes the neutral
    citation (e.g. `2024:CHC-AS:1277`). Just mention Calcutta and the side
    (appellate, original, Jalpaiguri, or Port Blair). See the
    [Calcutta HC guide](../guides/calcutta-hc.md).

!!! warning "Some PDFs are not uploaded"
    Even when a case exists, an individual order PDF may simply not have been uploaded to
    eCourts yet. The tool will give you the case and the order list; if a specific PDF
    isn't available, that's a gap on the portal, not an error on your end.

---

## 4. Precedent and research across the historical archive

This is where bharat-courts shines for research. It can query a complete historical
archive of judgments — the **Supreme Court from 1950 to the present, plus 25 High Courts**
— with no CAPTCHA and no rate limits. Search by judge, by year or year range, by citation,
or by keyword in the title.

```text
Find judgments authored by Justice Chandrachud in the Supreme Court between 2018 and 2024.
```

```text
Show me Delhi High Court judgments from 2020 whose title mentions Tata.
```

```text
Find Supreme Court judgments citing AIR 1973 — pull the citation and the outcome.
```

```text
Get me the PDF of the judgment with CNR DLHC010230802020.
```

```text
Find Supreme Court right-to-privacy judgments and download the Hindi-language versions.
```

**What comes back:** the matched judgments with decision date, case ID, title, citation,
and disposal outcome — and the assistant can fetch the full PDF for any of them. Supreme
Court judgments are also available in regional languages (Hindi, Tamil, Gujarat, and more);
High Court archive PDFs are English-only.

!!! note "Keyword search: title vs. full text"
    The historical archive matches keywords against the **case title and metadata**, not
    the full body of the judgment. For a true full-text search across the body of High
    Court judgments — "every case that mentions 'right to privacy' anywhere in the text" —
    the tool uses the live eCourts judgment-search portal instead. You can simply ask in
    plain English; the assistant picks the right source for you.

See the [Archive guide](../guides/archive.md) and the
[Judgment Search guide](../guides/judgment-search.md) for the full picture.

---

## 5. Recent Supreme Court judgments feed

Stay on top of what the Supreme Court has just delivered.

```text
Show me the 10 most recent Supreme Court judgments.
```

```text
What has the Supreme Court delivered this week? Download the PDFs.
```

```text
List the latest Supreme Court orders and tell me which are judgments vs. orders.
```

**What comes back:** the most recent items from the Supreme Court's official "Latest
Judgements / Orders" feed (up to 50) — each with the parties, case number, diary number,
decision date, and a downloadable PDF. No CAPTCHA needed for this one.

!!! info "Searching the Supreme Court by case or party"
    The recent-judgments feed is the supported way to pull fresh SCI items. Searching the
    Supreme Court by a specific case number or party name through the live portal is not
    wired up yet — for older SCI matters, use the historical archive (section 4), which
    goes back to 1950.

See the [Supreme Court guide](../guides/supreme-court.md).

---

## 6. Bulk and research-scale pulls

For power users — chambers running large research projects, legal-tech teams, or anyone
building a dataset — the tool can stream judgments at scale.

```text
Stream every Delhi High Court judgment from 2020 — there are around 18,000 — and save them.
```

```text
Count how many Supreme Court judgments were decided in 1975.
```

```text
Pull all judgments by a given judge across a five-year range and export them to a spreadsheet.
```

**What comes back:** results streamed in batches rather than all at once, so even
tens-of-thousands-of-row pulls stay manageable. Every result can be exported to JSON for
a spreadsheet, dashboard, or case-management tool.

!!! tip "This is genuinely fast"
    Because the archive is read directly from public data buckets, bulk pulls run in
    seconds with no portal load and no CAPTCHA — unlike the live portals, which are
    rate-limited and CAPTCHA-gated. If you're doing research at scale, ask for the
    archive. Engineers can see the streaming API in the
    [Archive guide](../guides/archive.md).

---

## Two honest limitations worth knowing

These aren't problems with the tool so much as facts about the underlying data. Keeping
them in mind will save you a surprise.

!!! tip "1. Freshness — the archive lags a couple of months"
    The historical archive is refreshed periodically (Supreme Court roughly every two
    months, High Courts roughly quarterly), so a judgment delivered in the **last 2–3
    months** may not be in it yet. When you ask about a very recent matter, the assistant
    will reach for the **live portals** instead. If a recent search comes back empty,
    just say "check the live portal too" — that's the right next move.

!!! tip "2. Always verify anything mission-critical"
    bharat-courts fetches data *from* the official eCourts and Supreme Court sources — it
    doesn't make anything up. But AI output is a powerful **research aid, not legal
    advice**. For anything that decides a filing, a limitation date, or a client's
    position, confirm the result against the official record or the case file before you
    rely on it.

---

## Where to go next

- New to all this? Start with [Using bharat-courts in Claude](claude-desktop.md).
- Questions about cost, privacy, and accuracy? See the [FAQ](faq.md).
- An engineer on your team wants the API? Point them at the
  [guides](../guides/facade.md).
