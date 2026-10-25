#!/usr/bin/env python3
"""Live checks for the judgments portal (judgments.ecourts.gov.in).

Covers ``JudgmentSearchClient`` (search, search_all, download_pdf), the
``live_to_judgment`` mapping and the live half of the ``Judgments`` facade.
Search phrases rotate daily so one phrase going stale cannot fail the backend.

Usage::

    python tests/integration/judgments.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import Check, Suite, first_working, require, rotate  # noqa: E402

require("ddddocr", "ocr")

suite = Suite(
    "Judgments portal live checks",
    results_dir="/tmp/bharat_courts_judgments_test",
    backend="judgments",
)

PHRASES = [
    "anticipatory bail",
    "specific performance",
    "writ of mandamus",
    "arbitral award",
    "dishonour of cheque",
    "compassionate appointment",
    "motor accident claims tribunal",
    "natural justice",
]
HC, SCR = "2", "3"
shared: dict = {}


def _client():
    from bharat_courts import JudgmentSearchClient

    return JudgmentSearchClient()


@suite.check("Keyword search — High Courts", "JudgmentSearchClient.search", "parse_search_response")
async def check_search_hc(c: Check) -> None:
    async with _client() as client:

        async def run(phrase: str):
            return await client.search(phrase, court_type=HC, page_size=10)

        phrase, result = await first_working(
            c, rotate(PHRASES), run, label="search", accept=lambda r: bool(r.items), max_tries=3
        )
    assert result is not None, "no phrase returned any High Court judgment"
    first = result.items[0]
    c.details["phrase"] = phrase
    c.details["total_count"] = result.total_count
    c.details["first"] = f"{first.judgment_date} {first.court_name} — {first.title[:60]}"
    assert first.title and first.court_name, "result row missing title / court"
    assert first.pdf_url, "result row carries no PDF path"
    assert first.metadata.get("pdf_val") is not None, "pdf_val missing — download would mis-index"
    shared["hc"] = (phrase, result)
    suite.save_json("search_hc", [j.to_dict(exclude_none=True) for j in result.items])
    c.passed = True


@suite.check("Keyword search — Supreme Court Reports", "JudgmentSearchClient.search(court_type=3)")
async def check_search_scr(c: Check) -> None:
    async with _client() as client:

        async def run(phrase: str):
            return await client.search(phrase, court_type=SCR, page_size=10)

        phrases = rotate(PHRASES)[1:] + rotate(PHRASES)[:1]
        phrase, result = await first_working(
            c, phrases, run, label="search", accept=lambda r: bool(r.items), max_tries=3
        )
    assert result is not None, "no phrase returned any SCR judgment"
    c.details["phrase"] = phrase
    c.details["total_count"] = result.total_count
    c.details["first"] = f"{result.items[0].judgment_date} — {result.items[0].title[:60]}"
    shared["scr"] = (phrase, result)
    c.passed = True


@suite.check("Paged iteration (search_all, 2 pages)", "JudgmentSearchClient.search_all")
async def check_search_all(c: Check) -> None:
    phrase = shared.get("hc", (rotate(PHRASES)[0], None))[0]
    seen: list[str] = []
    pages = 0
    async with _client() as client:
        async for page in client.search_all(phrase, court_type=HC, page_size=10):
            pages += 1
            seen.extend(j.source_id or j.title for j in page.items)
            c.details[f"page{pages}"] = f"{len(page.items)} rows, has_next={page.has_next}"
            if pages == 2 or not page.has_next:
                break
    c.details["rows"] = len(seen)
    c.details["unique"] = len(set(seen))
    assert pages >= 1 and seen, "search_all yielded nothing"
    assert len(set(seen)) == len(seen), "pages overlap — pagination is duplicating rows"
    c.passed = True


@suite.check("PDF download (two rows must differ)", "JudgmentSearchClient.download_pdf")
async def check_download_pdf(c: Check) -> None:
    _, result = shared.get("hc", (None, None))
    assert result is not None, "no search result to download from"
    rows = [j for j in result.items if j.pdf_url][:2]
    assert rows, "no row with a PDF path"
    async with _client() as client:
        # download_pdf resolves the row's path through openpdfcaptcha; the
        # session is per-client, so search again inside this client first.
        fresh = await client.search(shared["hc"][0], court_type=HC, page_size=10)
        rows = [j for j in fresh.items if j.pdf_url][:2]
        blobs = []
        for j in rows:
            await client.download_pdf(j, court_type=HC)
            assert j.pdf_bytes and j.pdf_bytes[:4] == b"%PDF", f"not a PDF: {j.title[:40]}"
            blobs.append(j.pdf_bytes)
            c.details[f"pdf[{j.source_id or j.title[:30]}]"] = f"{len(j.pdf_bytes):,} bytes"
    if len(blobs) == 2:
        # Regression: the portal keys temp files on the row's `val`; getting
        # it wrong serves the first row's PDF for every row.
        assert blobs[0] != blobs[1], "both rows returned identical PDF bytes (val indexing bug)"
    c.passed = True


@suite.check("live_to_judgment mapping", "live_to_judgment", "Judgment")
def check_live_to_judgment(c: Check) -> None:
    from bharat_courts.facade import live_to_judgment

    _, result = shared.get("hc", (None, None))
    assert result is not None, "no live rows to map"
    jr = result.items[0]
    j = live_to_judgment(jr)
    c.details["cnr"] = j.cnr
    c.details["court"] = j.court.code if j.court else f"unresolved ({j.court_name_raw!r})"
    c.details["decision_date"] = j.decision_date
    assert j.source == "live"
    assert j.cnr == (jr.source_id or None)
    assert j.title == jr.title
    assert j.to_json(), "Judgment.to_json failed"
    c.passed = True


@suite.check(
    "Facade: text routes to live; live PDF refused", "Judgments.find", "Judgments.fetch_pdf"
)
async def check_facade_live(c: Check) -> None:
    from bharat_courts import Judgments

    phrase = shared.get("hc", (rotate(PHRASES)[0], None))[0]
    async with Judgments() as j:
        hits = await j.find(text=phrase, limit=5)
        c.details["hits"] = len(hits)
        assert hits, "facade returned no live hits"
        assert all(h.source == "live" for h in hits), "text-only query did not route to live"
        try:
            await j.fetch_pdf(hits[0])
        except NotImplementedError:
            c.details["fetch_pdf(live)"] = "NotImplementedError (documented contract)"
        else:
            raise AssertionError("fetch_pdf on a live Judgment should raise NotImplementedError")
    c.passed = True


if __name__ == "__main__":
    suite.main()
