#!/usr/bin/env python3
"""Live checks for the Supreme Court site (www.sci.gov.in).

Covers ``SCIClient``: the homepage judgments feed, PDF download and the
documented not-implemented search surface.

Usage::

    python tests/integration/sci.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import Check, Suite  # noqa: E402

suite = Suite(
    "Supreme Court site live checks", results_dir="/tmp/bharat_courts_sci_test", backend="sci"
)
shared: dict = {}


@suite.check("Recent judgments feed", "SCIClient.list_recent_judgments", "parse_recent_judgments")
async def check_recent(c: Check) -> None:
    from bharat_courts import SCIClient

    async with SCIClient() as client:
        items = await client.list_recent_judgments(limit=10)
    c.details["items"] = len(items)
    assert items, "homepage feed parsed to zero items"
    first = items[0]
    c.details["first"] = f"{first.judgment_date} {first.case_number} — {first.title[:60]}"
    c.details["with_pdf"] = sum(1 for j in items if j.pdf_url)
    assert first.title, "first item has no title"
    assert any(j.pdf_url for j in items), "no item carries a PDF URL"
    shared["items"] = items
    suite.save_json("sci_recent", [j.to_dict(exclude_none=True) for j in items])
    c.passed = True


@suite.check("PDF download", "SCIClient.download_pdf")
async def check_pdf(c: Check) -> None:
    from bharat_courts import SCIClient

    items = [j for j in shared.get("items", []) if j.pdf_url]
    assert items, "no feed item with a PDF URL"
    async with SCIClient() as client:
        j = await client.download_pdf(items[0])
    assert j.pdf_bytes and j.pdf_bytes[:4] == b"%PDF", "download did not return a PDF"
    c.details["size"] = f"{len(j.pdf_bytes):,} bytes"
    c.details["case"] = j.case_number or j.title[:50]
    c.passed = True


@suite.check("Unsupported search raises NotImplementedError", "SCIClient.search_by_year")
async def check_unsupported(c: Check) -> None:
    from bharat_courts import SCIClient

    async with SCIClient() as client:
        for name, coro in (
            ("search_by_year", client.search_by_year(2024)),
            ("search_by_party", client.search_by_party("union of india")),
        ):
            try:
                await coro
            except NotImplementedError:
                c.details[name] = "NotImplementedError"
            else:
                raise AssertionError(f"{name} should raise NotImplementedError")
    c.passed = True


if __name__ == "__main__":
    suite.main()
