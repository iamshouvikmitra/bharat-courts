#!/usr/bin/env python3
"""Live checks for the archive module and the archive half of the facade.

Runs against the real AWS Open Data buckets (no AWS account needed) and
validates ``ArchiveClient`` (search, iter_judgments, count, fetch_pdf,
cache_info), the parquet / PDF caches, CNR prefix routing and the federated
``Judgments`` facade. The small High Court used for the cache / streaming /
PDF checks rotates daily.

Usage::

    pip install -e '.[archive,cli]'
    python tests/integration/archive.py

Runtime: ~30-45s cold (most of it the ~40 MB SCI 1950 English tar).
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _common import Check, Suite, first_working, require, rotate  # noqa: E402

require("duckdb", "archive")

CACHE_DIR = Path("/tmp/bharat_courts_archive_test")
if CACHE_DIR.exists():
    shutil.rmtree(CACHE_DIR)  # always start cold

suite = Suite("Archive + facade live checks", results_dir=CACHE_DIR / "_results", backend="archive")

# Small partitions keep cold queries fast; one of these is "today's court".
SMALL_HCS = ["manipur", "sikkim", "meghalaya", "tripura"]
HC = rotate(SMALL_HCS)[0]
YEAR = 2020
shared: dict = {}


def _client():
    from bharat_courts import ArchiveClient

    return ArchiveClient(cache_dir=str(CACHE_DIR))


@suite.check("Metadata search (SCI / Chandrachud / 2018-2024)", "ArchiveClient.search")
async def check_search(c: Check) -> None:
    async with _client() as a:
        hits = await a.search(court="sci", judge="chandrachud", year=(2018, 2024), limit=10)
    c.details["hits"] = len(hits)
    assert hits, "expected at least one hit"
    j = hits[0]
    c.details["first"] = f"{j.decision_date} {j.case_id} {(j.title or '')[:50]}"
    assert j.source == "archive" and j.court is not None and j.court.code == "sci"
    assert j.judges and "CHANDRACHUD" in j.judges[0].upper()
    c.passed = True


@suite.check("CNR prefix routing (SCI + HC, no court hint)", "infer_court_from_cnr", "search(cnr=)")
async def check_cnr_routing(c: Check) -> None:
    async with _client() as a:
        t0 = time.time()
        sci = await a.search(cnr="ESCR010000301950", limit=1)
        sci_t = time.time() - t0
        t0 = time.time()
        hc = await a.search(cnr="DLHC010230802020", limit=1)
        hc_t = time.time() - t0
    c.details["SCI"] = (
        f"{sci_t:.2f}s, {len(sci)} hit(s), court={sci[0].court.code if sci else 'n/a'}"
    )
    c.details["HC"] = f"{hc_t:.2f}s, {len(hc)} hit(s), court={hc[0].court.code if hc else 'n/a'}"
    assert len(sci) == 1 and sci[0].court.code == "sci"
    assert len(hc) == 1 and hc[0].court.code == "delhi"
    # Only a pathological regression (routing collapsing into a full
    # multi-partition scan) blows past this; cold S3 from CI is ~35s.
    assert sci_t < 60 and hc_t < 60, "CNR lookup pathologically slow — routing broke?"
    c.passed = True


@suite.check(f"Parquet cache cold → warm ({HC} {YEAR})", "_MetadataCache")
async def check_cache_speedup(c: Check) -> None:
    async with _client() as a:
        t0 = time.time()
        cold = await a.search(court=HC, year=YEAR, limit=5)
        cold_t = time.time() - t0
        t0 = time.time()
        warm = await a.search(court=HC, year=YEAR, limit=5)
        warm_t = time.time() - t0
    c.details["cold"] = f"{cold_t:.2f}s, {len(cold)} hit(s)"
    c.details["warm"] = f"{warm_t:.3f}s, {len(warm)} hit(s)"
    assert cold and warm
    assert warm_t < cold_t and warm_t < 1.0, f"warm hit unexpectedly slow ({warm_t:.2f}s)"
    shared["rows"] = cold
    c.passed = True


@suite.check(
    f"Streaming iterator ({HC} {YEAR}, batch=200, cap=600)", "ArchiveClient.iter_judgments"
)
async def check_iter(c: Check) -> None:
    count = 0
    cnrs: set[str] = set()
    async with _client() as a:
        async for j in a.iter_judgments(court=HC, year=YEAR, batch_size=200, max_results=600):
            count += 1
            if j.cnr:
                cnrs.add(j.cnr)
    c.details["yielded"] = count
    c.details["unique_cnrs"] = len(cnrs)
    assert count > 0
    assert count == 600 or count == len(cnrs), "pagination duplicating rows?"
    shared["iter_count"] = count
    c.passed = True


@suite.check("Row counts (count)", "ArchiveClient.count")
async def check_count(c: Check) -> None:
    async with _client() as a:
        hc = await a.count(court=HC, year=YEAR)
        sci = await a.count(court="sci", year=1950)
    c.details[f"{HC} {YEAR}"] = hc
    c.details["sci 1950"] = sci
    assert hc.get("hc", 0) > 0 and "sci" not in hc
    assert sci.get("sci", 0) > 0 and "hc" not in sci
    streamed = shared.get("iter_count")
    if streamed is not None and streamed < 600:
        assert hc["hc"] == streamed, f"count {hc['hc']} != streamed {streamed}"
    c.passed = True


@suite.check(f"HC PDF fetch ({HC} {YEAR}, from a search row)", "ArchiveClient.fetch_pdf(HC)")
async def check_hc_pdf(c: Check) -> None:
    rows = shared.get("rows") or []
    assert rows, "no rows from the cache check to fetch"
    async with _client() as a:

        async def fetch(j):
            return await a.fetch_pdf(j)

        # pdf_exists in the parquet is unreliable — bucket reality wins, so
        # try a few rows rather than pre-filtering.
        j, data = await first_working(
            c, rows, fetch, label="pdf", key=lambda j: j.cnr or "?", max_tries=3
        )
    assert data is not None, "none of the sampled rows had a fetchable PDF"
    assert data[:4] == b"%PDF" and len(data) > 1000
    c.details["cnr"] = j.cnr
    c.details["size"] = f"{len(data):,} bytes"
    c.passed = True


@suite.check("SCI PDF fetch (1950 English, ~40 MB tar)", "ArchiveClient.fetch_pdf(SCI)")
async def check_sci_pdf(c: Check) -> None:
    async with _client() as a:
        t0 = time.time()
        d1 = await a.fetch_pdf("ESCR010000301950", language="english")
        tar_t = time.time() - t0
        t0 = time.time()
        d2 = await a.fetch_pdf("ESCR010000031950", language="english")
        warm_t = time.time() - t0
    c.details["first"] = f"{len(d1):,} bytes in {tar_t:.1f}s (tar download)"
    c.details["second"] = f"{len(d2):,} bytes in {warm_t:.2f}s (cached tar)"
    assert d1[:4] == b"%PDF" and d2[:4] == b"%PDF"
    assert warm_t < tar_t / 2, "second fetch should reuse the cached tar"
    c.passed = True


@suite.check("Cache accounting (cache_info)", "ArchiveClient.cache_info")
async def check_cache_info(c: Check) -> None:
    async with _client() as a:
        info = a.cache_info()
    c.details["info"] = info
    assert info["files"] > 0 and info["bytes"] > 0, "cache should hold parquet + tar + pdf"
    assert info["max_bytes"] > info["bytes"], "cache already over its cap?"
    assert Path(info["cache_dir"]) == CACHE_DIR
    c.passed = True


@suite.check("Facade routing (structured / CNR / mixed / forced / empty)", "Judgments.find")
async def check_facade(c: Check) -> None:
    from bharat_courts import Judgments

    async with Judgments() as j:
        structured = await j.find(judge="chandrachud", year=2022, court="sci", limit=2)
        cnr = await j.find(cnr="DLHC010230802020", limit=1)
        mixed = await j.find(text="asian hotels", court="delhi", year=2020, limit=3)
        forced = await j.find(text="union of india", court=HC, year=YEAR, source="archive", limit=3)
        try:
            await j.find()
        except ValueError:
            c.details["find()"] = "ValueError (documented)"
        else:
            raise AssertionError("find() with no filters should raise ValueError")
        pdf = await j.fetch_pdf("DLHC010230802020")
    c.details["structured"] = len(structured)
    c.details["cnr"] = len(cnr)
    c.details["mixed"] = len(mixed)
    c.details["forced archive"] = len(forced)
    c.details["fetch_pdf"] = f"{len(pdf):,} bytes"
    assert structured and all(r.source == "archive" for r in structured)
    assert len(cnr) == 1 and cnr[0].source == "archive"
    assert mixed and all(r.source == "archive" for r in mixed)
    assert all(r.source == "archive" for r in forced)
    assert pdf[:4] == b"%PDF"
    c.passed = True


if __name__ == "__main__":
    suite.main()
