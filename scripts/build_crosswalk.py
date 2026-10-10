#!/usr/bin/env python3
"""Rebuild ``src/bharat_courts/data/crosswalk.csv`` from the source tables.

The crosswalk maps sections of the three codes repealed on 1 July 2024 to
their successors: IPC → BNS, CrPC → BNSS, Indian Evidence Act → BSA. It is
generated from the correspondence tables published by the Central Academy
for Police Training (CAPT), Bhopal — never edited by hand — so a correction
means fixing this script or the source, then regenerating.

Usage (maintainers only; needs ``pip install pdfplumber``)::

    python scripts/build_crosswalk.py BNS_to_IPC.pdf BNSS_to_CrPC.pdf BSA_to_IEA.pdf

The PDFs are at ``SOURCES`` below. Cells the parser can't read cleanly are
printed so they can be checked by eye against the PDF.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pdfplumber

OUT = Path(__file__).resolve().parent.parent / "src" / "bharat_courts" / "data" / "crosswalk.csv"

_BASE = "https://keralaprisons.gov.in/userfiles/act-and-rules/"

#: (old act key, new act key, source URL, index of the old-section cell).
#: Rows normalise to [new, ·, ·, summary]: BNS and BNSS put the old section
#: third (after the subject), the BSA table second (before it).
SOURCES = [
    ("ipc", "bns", _BASE + "comparison_summary_BNS_to_IPC.pdf", 2),
    ("crpc", "bnss", _BASE + "comparison_summary_BNSS_to_CrPC.pdf", 2),
    ("iea", "bsa", _BASE + "comparison_summary_BSA_to_IEA.pdf", 1),
]

#: A section number: digits plus an optional letter suffix (498A, 65B, 304AA).
_SECTION = re.compile(r"^\d+[A-Z]{0,2}$")


def _rows(pdf_path: str) -> list[tuple[int, list[str]]]:
    """Table rows as (page number, four cleaned cells).

    Most rows have four cells. Two six-cell layouts also occur: the BNS
    table's first page has two empty spacer columns after the section
    (``[new, "", "", subject, old, summary]``), and some BNSS pages have a
    spill-over column for long summaries (``[new, subject, old, summary,
    extra, ""]``). Single-cell rows are wrapped summary text and dropped.
    """
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for raw in table:
                    cells = [re.sub(r"\s+", " ", c or "").strip() for c in raw]
                    if len(cells) == 6 and not cells[1] and not cells[2]:
                        cells = [cells[0], cells[3], cells[4], cells[5]]
                    elif len(cells) == 6:
                        cells = cells[:4]
                    if len(cells) == 4:
                        out.append((page_no, cells))
    return out


def _old_sections(cell: str) -> list[str]:
    """Old-code section numbers named in a cell.

    ``376(1) & 376(2)`` → ``["376"]``; ``29 and 29A`` → ``["29", "29A"]``;
    ``3, para 1`` and ``23 Clause-1`` → ``["3"]`` / ``["23"]``;
    ``171-I`` → ``["171I"]``; ``230 to 232`` → ``["230", "231", "232"]``.
    Subsection brackets and para/clause references are dropped first, so
    their numbers aren't read as sections.
    """
    cell = re.sub(r"\([^)]*\)", " ", cell)
    cell = re.sub(r"\b(?:para|clause)[\s-]*\d+", " ", cell, flags=re.I)
    cell = re.sub(r"\b(\d+)-([A-Z]{1,2})\b", r"\1\2", cell.upper())
    cell = re.sub(
        r"\b(\d+) TO (\d+)\b",
        lambda m: " ".join(str(n) for n in range(int(m[1]), int(m[2]) + 1)),
        cell,
    )
    seen: list[str] = []
    for token in re.findall(r"\b\d+[A-Z]{0,2}\b", cell):
        if token not in seen:
            seen.append(token)
    return seen


def _new_section(cell: str) -> tuple[str, str]:
    """``"103 (1)"`` → (``"103(1)"``, ``"103"``). Base is ``""`` if unreadable.

    Provisos and explanations are named in words — ``"Proviso to section
    23"`` (IEA 27) — so those keep their wording and take the base from the
    section they attach to.
    """
    compact = re.sub(r"\s+", "", cell)
    m = re.match(r"(\d+[A-Z]{0,2})", compact)
    if m:
        return compact, m.group(1)
    m = re.search(r"\bto section\s*(\d+[A-Z]{0,2})", cell, flags=re.I)
    if m:
        # pdfplumber splits long words across lines ("Explanati on").
        words = re.sub(r"\b(Explanati) (on)\b", r"\1\2", " ".join(cell.split()))
        return words, m.group(1)
    return compact, ""


def build(paths: list[str]) -> list[dict]:
    records: list[dict] = []
    for (old_act, new_act, url, old_index), path in zip(SOURCES, paths, strict=True):
        for page, cells in _rows(path):
            old_cell = cells[old_index]
            new_raw, new_base = _new_section(cells[0])
            if not new_base:
                continue  # header rows ("BNS Sections") and continuations
            olds = _old_sections(old_cell)
            if not olds:
                continue  # "New", "-": no predecessor
            flag = "" if _SECTION.match(old_cell.replace(" ", "")) else "  <- check"
            if flag:
                print(f"{old_act} p{page}: old={old_cell!r} -> {olds}  new={new_raw}{flag}")
            for old in olds:
                records.append(
                    {
                        "old_act": old_act,
                        "old_section": old,
                        "new_act": new_act,
                        "new_section": new_raw,
                        "new_section_base": new_base,
                        "source_page": page,
                        "source": url,
                    }
                )
    return records


def main(argv: list[str]) -> None:
    if len(argv) != len(SOURCES):
        sys.exit(__doc__)
    records = build(argv)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        fh.write(
            "# Generated by scripts/build_crosswalk.py — do not edit by hand.\n"
            "# Source: correspondence tables by the Central Academy for Police Training,\n"
            "# Bhopal (Anil Kishore Yadav, IPS), as published at the 'source' URLs.\n"
        )
        writer = csv.DictWriter(fh, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    print(f"wrote {len(records)} rows to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
