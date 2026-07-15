#!/usr/bin/env python3
"""Comprehensive live test of bharat-courts archive + facade.

Runs against the real AWS Open Data buckets (no AWS account needed) and
validates the archive module, parquet/PDF caches, CNR prefix routing, the
streaming iterator, and the federated ``Judgments`` facade.

Usage::

    cd bharat-courts
    source .venv/bin/activate
    pip install -e '.[archive,cli]'
    python tests/integration/archive.py

Total runtime: ~30-45 seconds on a warm internet connection (most of that
is the ~40 MB SCI 1950 English tar; subsequent runs hit the cache and
finish in ~5s).

Tests:
  1. Archive metadata search (DuckDB over S3, no PDFs)
  2. CNR prefix routing (avoids the all-HC-partition scan)
  3. Parquet cache speedup (cold → warm)
  4. Streaming iterator with batch pagination
  5. HC PDF fetch (single direct GET)
  6. SCI PDF fetch (downloads the year tar on first call)
  7. Federated facade routing (structured + CNR + mixed)
"""

import asyncio
import shutil
import sys
import time
import traceback
from pathlib import Path

# --- Setup ---

CACHE_DIR = Path("/tmp/bharat_courts_archive_test")
if CACHE_DIR.exists():
    shutil.rmtree(CACHE_DIR)  # always start cold

try:
    import bharat_courts  # noqa: F401
    from bharat_courts import ArchiveClient, Judgments
except ImportError as e:
    print(f"ERROR: {e}", file=sys.stderr)
    print(
        "Install with: pip install -e '.[archive,cli]'",
        file=sys.stderr,
    )
    sys.exit(1)


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error = ""
        self.details: dict = {}
        self.elapsed = 0.0

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        s = f"[{status}] {self.name}  ({self.elapsed:.2f}s)"
        if self.error:
            s += f"\n       ERROR: {self.error}"
        for k, v in self.details.items():
            s += f"\n       {k}: {v}"
        return s


results: list[TestResult] = []


def _time(coro):
    """Run an async coroutine and return (value, elapsed_seconds)."""
    t0 = time.time()
    value = asyncio.run(coro)
    return value, time.time() - t0


# --- Test functions ---


async def test_metadata_search():
    """Test 1: SQL-only search against SCI parquet."""
    t = TestResult("Archive metadata search (SCI / Chandrachud / 2018-2024)")
    try:
        async with ArchiveClient(cache_dir=str(CACHE_DIR)) as c:
            t0 = time.time()
            hits = await c.search(court="sci", judge="chandrachud", year=(2018, 2024), limit=10)
            t.elapsed = time.time() - t0
        t.details["hits"] = len(hits)
        if hits:
            j = hits[0]
            t.details["first"] = f"{j.decision_date} {j.case_id} {(j.title or '')[:50]}"
            assert j.source == "archive"
            assert j.court is not None and j.court.code == "sci"
            assert "CHANDRACHUD" in (j.judges[0].upper() if j.judges else "")
        assert len(hits) > 0, "expected at least one hit"
        t.passed = True
    except Exception as e:  # noqa: BLE001 - any error is a test failure
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_cnr_prefix_routing():
    """Test 2: CNR-only lookups for SCI + HC — verifies prefix routing."""
    t = TestResult("CNR prefix routing (SCI + HC, no court hint)")
    try:
        async with ArchiveClient(cache_dir=str(CACHE_DIR)) as c:
            # SCI CNR
            t0 = time.time()
            sci_hits = await c.search(cnr="ESCR010000301950", limit=1)
            sci_elapsed = time.time() - t0
            t.details["SCI"] = (
                f"{sci_elapsed:.2f}s, {len(sci_hits)} hit(s), "
                f"court={sci_hits[0].court.code if sci_hits else 'n/a'}"
            )
            # HC CNR (Delhi)
            t0 = time.time()
            hc_hits = await c.search(cnr="DLHC010230802020", limit=1)
            hc_elapsed = time.time() - t0
            t.details["HC"] = (
                f"{hc_elapsed:.2f}s, {len(hc_hits)} hit(s), "
                f"court={hc_hits[0].court.code if hc_hits else 'n/a'}"
            )
            t.elapsed = sci_elapsed + hc_elapsed
        # Correctness IS the routing check: a resolved prefix hits exactly the
        # right court's partition. If routing broke and fell back to a full
        # multi-source scan we'd get the wrong/no court here.
        assert len(sci_hits) == 1 and sci_hits[0].court.code == "sci"
        assert len(hc_hits) == 1 and hc_hits[0].court.code == "delhi"
        # A generous latency ceiling only to catch a *pathological* regression
        # (routing collapsing into a full unpartitioned scan takes minutes).
        # NOT a tight perf gate — cold S3 from a fresh CI runner is ~35s, which
        # is fine; only a genuine routing break blows past 60s.
        assert sci_elapsed < 60, f"SCI CNR pathologically slow ({sci_elapsed:.2f}s)"
        assert hc_elapsed < 60, f"HC CNR pathologically slow ({hc_elapsed:.2f}s)"
        t.passed = True
    except Exception as e:  # noqa: BLE001
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_parquet_cache_speedup():
    """Test 3: Run the same query twice; warm hit must be much faster."""
    t = TestResult("Parquet cache cold → warm speedup")
    try:
        async with ArchiveClient(cache_dir=str(CACHE_DIR)) as c:
            # Use a court+year we haven't queried yet so the cache is cold.
            t0 = time.time()
            cold = await c.search(court="manipur", year=2020, limit=5)
            cold_t = time.time() - t0
            t0 = time.time()
            warm = await c.search(court="manipur", year=2020, limit=5)
            warm_t = time.time() - t0
            t.elapsed = cold_t + warm_t
        t.details["cold"] = f"{cold_t:.2f}s, {len(cold)} hit(s)"
        t.details["warm"] = f"{warm_t:.3f}s, {len(warm)} hit(s)"
        t.details["speedup"] = f"{cold_t / warm_t:.0f}x" if warm_t > 0 else "n/a"
        assert len(cold) > 0 and len(warm) > 0
        assert warm_t < cold_t, "warm should be faster than cold"
        # Warm should be sub-second; cold can be 1-5s depending on network.
        assert warm_t < 1.0, f"warm hit unexpectedly slow ({warm_t:.2f}s)"
        t.passed = True
    except Exception as e:  # noqa: BLE001
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_streaming_iterator():
    """Test 4: iter_judgments — page through results, respect max_results."""
    t = TestResult("Streaming iterator (Manipur 2020, batch_size=200, cap=600)")
    try:
        async with ArchiveClient(cache_dir=str(CACHE_DIR)) as c:
            t0 = time.time()
            count = 0
            seen_cnrs: set[str] = set()
            async for j in c.iter_judgments(
                court="manipur", year=2020, batch_size=200, max_results=600
            ):
                count += 1
                if j.cnr:
                    seen_cnrs.add(j.cnr)
            t.elapsed = time.time() - t0
        t.details["yielded"] = count
        t.details["unique_cnrs"] = len(seen_cnrs)
        assert count == 600 or count == len(seen_cnrs), (
            f"got {count} judgments but {len(seen_cnrs)} unique CNRs — pagination duplicating?"
        )
        t.passed = True
    except Exception as e:  # noqa: BLE001
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_hc_pdf_fetch():
    """Test 5: Fetch a single HC PDF (direct GET, no tar)."""
    t = TestResult("HC PDF fetch (Delhi 2020, single GET)")
    try:
        async with ArchiveClient(cache_dir=str(CACHE_DIR)) as c:
            t0 = time.time()
            data = await c.fetch_pdf("DLHC010230802020")
            t.elapsed = time.time() - t0
        t.details["size"] = f"{len(data):,} bytes"
        t.details["head"] = repr(data[:8])
        assert data.startswith(b"%PDF"), f"not a PDF (head={data[:32]!r})"
        assert len(data) > 1000, "PDF suspiciously small"
        t.passed = True
    except Exception as e:  # noqa: BLE001
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_sci_pdf_fetch():
    """Test 6: Fetch a SCI PDF (downloads ~40 MB year tar on first run)."""
    t = TestResult("SCI PDF fetch (1950 English; downloads ~40 MB tar)")
    try:
        async with ArchiveClient(cache_dir=str(CACHE_DIR)) as c:
            t0 = time.time()
            data = await c.fetch_pdf("ESCR010000301950", language="english")
            tar_t = time.time() - t0
            # A second fetch in the same year should be tar-extraction-fast.
            t0 = time.time()
            data2 = await c.fetch_pdf("ESCR010000031950", language="english")
            warm_t = time.time() - t0
            t.elapsed = tar_t + warm_t
        t.details["first_size"] = f"{len(data):,} bytes"
        t.details["first_elapsed"] = f"{tar_t:.2f}s (includes tar download)"
        t.details["second_size"] = f"{len(data2):,} bytes"
        t.details["second_elapsed"] = f"{warm_t:.2f}s (tar already cached)"
        assert data.startswith(b"%PDF") and data2.startswith(b"%PDF")
        assert warm_t < tar_t / 2, "second fetch should reuse cached tar"
        t.passed = True
    except Exception as e:  # noqa: BLE001
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


async def test_federated_facade():
    """Test 7: Judgments.find — structured / CNR / mixed routing."""
    t = TestResult("Federated facade (Judgments.find)")
    try:
        async with Judgments() as j:
            # Structured → archive
            t0 = time.time()
            structured = await j.find(judge="chandrachud", year=2022, court="sci", limit=2)
            struct_t = time.time() - t0

            # CNR → archive via prefix
            t0 = time.time()
            cnr_hits = await j.find(cnr="DLHC010230802020", limit=1)
            cnr_t = time.time() - t0

            # Mixed → archive with title fallback
            t0 = time.time()
            mixed = await j.find(text="asian hotels", court="delhi", year=2020, limit=3)
            mixed_t = time.time() - t0

            t.elapsed = struct_t + cnr_t + mixed_t
        t.details["structured"] = f"{struct_t:.2f}s, {len(structured)} hit(s)"
        t.details["cnr"] = f"{cnr_t:.2f}s, {len(cnr_hits)} hit(s)"
        t.details["mixed"] = f"{mixed_t:.2f}s, {len(mixed)} hit(s)"
        assert len(structured) > 0 and all(r.source == "archive" for r in structured)
        assert len(cnr_hits) == 1 and cnr_hits[0].source == "archive"
        assert len(mixed) > 0 and all(r.source == "archive" for r in mixed)
        t.passed = True
    except Exception as e:  # noqa: BLE001
        t.error = f"{type(e).__name__}: {e}"
        traceback.print_exc()
    results.append(t)


# --- Main ---


async def run_all():
    print("=" * 70)
    print("  bharat-courts — Archive + Facade live integration test")
    print(f"  Version: {bharat_courts.__version__}")
    print(f"  Cache:   {CACHE_DIR} (cleared at start)")
    print("=" * 70)
    print()

    tests = [
        ("1/7", test_metadata_search),
        ("2/7", test_cnr_prefix_routing),
        ("3/7", test_parquet_cache_speedup),
        ("4/7", test_streaming_iterator),
        ("5/7", test_hc_pdf_fetch),
        ("6/7", test_sci_pdf_fetch),
        ("7/7", test_federated_facade),
    ]
    for label, func in tests:
        print(f"[{label}] {func.__doc__.splitlines()[0].strip()}")
        await func()
        print(f"  {results[-1]}")
        print()

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    total_elapsed = sum(r.elapsed for r in results)
    print("=" * 70)
    print(f"  Results: {passed}/{total} passed  ({total_elapsed:.1f}s total)")
    print("=" * 70)
    return passed == total


def main():
    success = asyncio.run(run_all())
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
