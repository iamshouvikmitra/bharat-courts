"""Unit tests for the quick-wins bundle: CNR routing, streaming, parquet cache.

All tests are offline. Network is mocked via respx where needed; the parquet
cache is exercised against a synthetic local file tree.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from bharat_courts.archive.client import ArchiveClient
from bharat_courts.archive.metadata import _ArchiveQuery, _from_clause
from bharat_courts.archive.metadata_cache import _MetadataCache
from bharat_courts.courts import (
    _CNR_PREFIX_TO_COURT_CODE,
    SUPREME_COURT,
    get_court,
    infer_court_from_cnr,
)

# ===========================================================================
# 1. CNR prefix routing
# ===========================================================================


def test_infer_court_from_sci_cnr():
    assert infer_court_from_cnr("ESCR010000301950") == SUPREME_COURT


@pytest.mark.parametrize(
    "cnr, expected_code",
    [
        ("DLHC010230802020", "delhi"),
        ("MNHC010001072018", "manipur"),
        ("HCBM020056322016", "bombay"),
        ("HCMA013640862018", "madras"),
        ("HBHC010013262020", "telangana"),
        ("WBCHCJ0008142019", "calcutta"),
        ("GAHC040003412019", "gauhati"),
        ("PHHC010590592020", "punjab"),
    ],
)
def test_infer_court_from_hc_cnr(cnr: str, expected_code: str):
    court = infer_court_from_cnr(cnr)
    assert court is not None
    assert court.code == expected_code


def test_infer_court_handles_lowercase():
    assert infer_court_from_cnr("dlhc010230802020") is not None


def test_infer_court_returns_none_for_unknown():
    assert infer_court_from_cnr("ZZZZ012345") is None
    assert infer_court_from_cnr(None) is None
    assert infer_court_from_cnr("") is None
    assert infer_court_from_cnr("DL") is None  # too short


def test_cnr_prefix_map_covers_all_courts():
    """Every court in the prefix map resolves to a real Court object.

    Guards against typos in the static map.
    """
    for prefix, code in _CNR_PREFIX_TO_COURT_CODE.items():
        assert get_court(code) is not None, f"CNR prefix {prefix!r} → unknown court code {code!r}"


def test_cnr_prefix_map_has_all_25_hcs_plus_sci():
    """Sanity: 25 HCs + SCI = 26 entries."""
    assert len(_CNR_PREFIX_TO_COURT_CODE) == 26


# ===========================================================================
# 2. Streaming iterator — query-builder offset
# ===========================================================================


@pytest.fixture
def query():
    return _ArchiveQuery()


def test_sci_query_includes_offset_and_stable_sort(query):
    sql, _ = query._build_sci_query(
        year=2020,
        judge=None,
        party=None,
        citation=None,
        cnr=None,
        limit=100,
        offset=250,
    )
    assert "LIMIT 100 OFFSET 250" in sql
    # Stable sort is what makes LIMIT/OFFSET pagination deterministic.
    assert "ORDER BY decision_date DESC NULLS LAST, cnr" in sql


def test_hc_query_includes_offset_and_stable_sort(query):
    sql, _ = query._build_hc_query(
        court=None,
        year=2020,
        judge=None,
        party=None,
        cnr=None,
        limit=50,
        offset=500,
    )
    assert "LIMIT 50 OFFSET 500" in sql
    assert "ORDER BY decision_date DESC NULLS LAST, cnr" in sql


def test_offset_defaults_to_zero(query):
    sql, _ = query._build_sci_query(
        year=2020,
        judge=None,
        party=None,
        citation=None,
        cnr=None,
        limit=10,
    )
    assert "OFFSET 0" in sql


# ===========================================================================
# 2. Streaming iterator — end-to-end (mocked _ArchiveQuery)
# ===========================================================================


@pytest.mark.asyncio
async def test_iter_judgments_pages_through_one_source():
    """Three pages of fake SCI rows; iterator emits everything across pages."""

    def fake_sci_pages(*, limit, offset, **kw):
        # 1100 total rows, batch_size=500 → pages of 500, 500, 100.
        total = 1100
        start = offset
        end = min(start + limit, total)
        return [
            {
                "cnr": f"ESCR{i:012d}",
                "case_id": f"FAKE{i}",
                "title": f"t{i}",
                "petitioner": "p",
                "respondent": "r",
                "judge": "j",
                "decision_date": "01-01-2020",
                "court": "Supreme Court of India",
                "year": "2020",
            }
            for i in range(start, end)
        ]

    client = ArchiveClient.__new__(ArchiveClient)  # bypass __init__
    client._query = AsyncMock()
    client._query.search_sci = fake_sci_pages
    # Stub the cache/storage so close() and helpers don't blow up.
    client._meta_cache = None
    client._storage = AsyncMock()
    client._storage.aclose = AsyncMock()

    seen: list[str] = []
    async for j in client.iter_judgments(court="sci", year=2020, batch_size=500):
        seen.append(j.cnr)
    assert len(seen) == 1100
    # No duplicates — pagination is stable.
    assert len(set(seen)) == 1100


@pytest.mark.asyncio
async def test_iter_judgments_respects_max_results():
    def fake_pages(*, limit, offset, **kw):
        return [
            {
                "cnr": f"ESCR{i:012d}",
                "title": f"t{i}",
                "judge": "j",
                "decision_date": "01-01-2020",
                "court": "Supreme Court of India",
                "year": "2020",
            }
            for i in range(offset, offset + limit)
        ]  # infinite

    client = ArchiveClient.__new__(ArchiveClient)
    client._query = AsyncMock()
    client._query.search_sci = fake_pages
    client._meta_cache = None
    client._storage = AsyncMock()

    seen: list[str] = []
    async for j in client.iter_judgments(court="sci", year=2020, batch_size=100, max_results=250):
        seen.append(j.cnr)
    assert len(seen) == 250


@pytest.mark.asyncio
async def test_iter_judgments_routes_cnr_via_prefix():
    """CNR-only call should set court via prefix and skip SCI when CNR is HC."""
    sci_calls = 0
    hc_calls = 0

    def fake_sci(*, limit, offset, **kw):
        nonlocal sci_calls
        sci_calls += 1
        return []

    def fake_hc(*, limit, offset, court, **kw):
        nonlocal hc_calls
        hc_calls += 1
        # Assert the resolved court was passed in.
        assert court is not None and court.code == "delhi"
        return [
            {
                "cnr": "DLHC010230802020",
                "court_code": "7~26",
                "judge": "j",
                "decision_date": "01-01-2020",
                "year": "2020",
                "bench": "dhcdb",
                "title": "t",
                "pdf_link": "x",
                "pdf_exists": True,
            }
        ]

    client = ArchiveClient.__new__(ArchiveClient)
    client._query = AsyncMock()
    client._query.search_sci = fake_sci
    client._query.search_hc = fake_hc
    client._meta_cache = None
    client._storage = AsyncMock()

    items = [j async for j in client.iter_judgments(cnr="DLHC010230802020")]
    assert len(items) == 1
    assert sci_calls == 0, "should NOT scan SCI for an HC CNR"
    assert hc_calls >= 1


# ===========================================================================
# 3. Parquet shard cache — _from_clause + _MetadataCache
# ===========================================================================


def test_from_clause_uses_glob_by_default():
    clause = _from_clause("s3://b/foo/*.parquet", None)
    assert "read_parquet('s3://b/foo/*.parquet'" in clause


def test_from_clause_uses_paths_override(tmp_path: Path):
    paths = [tmp_path / "a.parquet", tmp_path / "b.parquet"]
    clause = _from_clause("s3://ignored", paths)
    assert "['" in clause  # list form
    assert "a.parquet" in clause and "b.parquet" in clause
    # Glob is NOT used when paths_override is given.
    assert "s3://ignored" not in clause


@pytest.mark.asyncio
async def test_metadata_cache_uses_cached_file_within_ttl(tmp_path: Path):
    """A fresh-enough cached file should not trigger a re-fetch."""
    cache = _MetadataCache(cache_dir=tmp_path, ttl_seconds=3600)
    # Pre-seed the cache.
    target = tmp_path / "sci" / "year=2020" / "metadata.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"cached-payload")

    # Any HTTP call would fail this test (500 is unmocked → respx raises).
    with respx.mock(assert_all_called=False) as m:
        m.get(url__regex=r"https://indian-supreme-court-judgments\.s3\..*").mock(
            return_value=httpx.Response(500)
        )
        paths = await cache.get_sci_paths(2020)

    assert paths == [target]
    assert target.read_bytes() == b"cached-payload"
    await cache.aclose()


@pytest.mark.asyncio
async def test_metadata_cache_refetches_when_stale(tmp_path: Path):
    cache = _MetadataCache(cache_dir=tmp_path, ttl_seconds=0)  # always stale
    target = tmp_path / "sci" / "year=2020" / "metadata.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"OLD")

    with respx.mock:
        respx.get(url__regex=r"https://indian-supreme-court-judgments\.s3\..*").mock(
            return_value=httpx.Response(200, content=b"NEW")
        )
        paths = await cache.get_sci_paths(2020)

    assert paths == [target]
    assert target.read_bytes() == b"NEW"
    await cache.aclose()


@pytest.mark.asyncio
async def test_metadata_cache_skips_404_silently(tmp_path: Path):
    """If a particular year has no shard, return an empty list — don't crash."""
    cache = _MetadataCache(cache_dir=tmp_path, ttl_seconds=3600)
    with respx.mock:
        respx.get(url__regex=r"https://indian-supreme-court-judgments\.s3\..*").mock(
            return_value=httpx.Response(404)
        )
        paths = await cache.get_sci_paths(9999)
    assert paths == []
    await cache.aclose()


@pytest.mark.asyncio
async def test_metadata_cache_hc_uses_state_filter(tmp_path: Path):
    """HC path resolution needs the listing + a per-bench download."""
    cache = _MetadataCache(cache_dir=tmp_path, ttl_seconds=3600)

    # Pre-seed BOTH listing caches so we don't need to mock S3 LIST.
    courts_path = tmp_path / "_listings" / "hc_courts_year=2020.json"
    courts_path.parent.mkdir(parents=True, exist_ok=True)
    courts_path.write_text(json.dumps({"26": "7"}))  # delhi → archive id 7

    benches_path = tmp_path / "_listings" / "hc_benches_year=2020_court=7_26.json"
    benches_path.write_text(json.dumps(["dhcdb"]))

    delhi = get_court("delhi")
    with respx.mock:
        respx.get(url__regex=r"https://indian-high-court-judgments\.s3\..*").mock(
            return_value=httpx.Response(200, content=b"PARQUET-BYTES")
        )
        paths = await cache.get_hc_paths(2020, delhi)

    assert len(paths) == 1
    assert paths[0].name == "metadata.parquet"
    assert "court=7_26" in str(paths[0])
    assert "bench=dhcdb" in str(paths[0])
    assert paths[0].read_bytes() == b"PARQUET-BYTES"
    await cache.aclose()


@pytest.mark.asyncio
async def test_metadata_cache_hc_skips_courts_with_no_archive_data(tmp_path: Path):
    """If the state isn't in that year's listing, return [] without raising."""
    cache = _MetadataCache(cache_dir=tmp_path, ttl_seconds=3600)
    courts_path = tmp_path / "_listings" / "hc_courts_year=2020.json"
    courts_path.parent.mkdir(parents=True, exist_ok=True)
    courts_path.write_text(json.dumps({"99": "999"}))  # delhi (26) not present

    paths = await cache.get_hc_paths(2020, get_court("delhi"))
    assert paths == []
    await cache.aclose()


# ===========================================================================
# 3. Cache wiring: search/iter call paths_override only when partition is full
# ===========================================================================


@pytest.mark.asyncio
async def test_client_skips_cache_when_year_missing(tmp_path: Path):
    """No year → no cache lookup → query gets paths_override=None."""
    client = ArchiveClient(cache_dir=tmp_path, metadata_cache=True)
    sci = await client._sci_paths_for_cache(year=None)
    hc = await client._hc_paths_for_cache(get_court("delhi"), year=None)
    assert sci is None
    assert hc is None
    await client.close()


@pytest.mark.asyncio
async def test_client_skips_hc_cache_when_court_missing(tmp_path: Path):
    """No court → HC cache not used (would download too many shards)."""
    client = ArchiveClient(cache_dir=tmp_path, metadata_cache=True)
    hc = await client._hc_paths_for_cache(None, year=2020)
    assert hc is None
    await client.close()


@pytest.mark.asyncio
async def test_client_uses_cache_when_partition_fully_specified(tmp_path: Path):
    """With year+court given, the cache helper is consulted."""
    client = ArchiveClient(cache_dir=tmp_path, metadata_cache=True)

    fake_paths = [tmp_path / "fake.parquet"]
    with patch.object(
        client._meta_cache, "get_hc_paths", new=AsyncMock(return_value=fake_paths)
    ) as p:
        paths = await client._hc_paths_for_cache(get_court("delhi"), year=2020)
    p.assert_awaited_once()
    assert paths == fake_paths
    await client.close()


@pytest.mark.asyncio
async def test_client_cache_failure_falls_back_to_glob(tmp_path: Path):
    """Cache errors should never break queries — fall back to S3 glob."""
    client = ArchiveClient(cache_dir=tmp_path, metadata_cache=True)
    with patch.object(
        client._meta_cache,
        "get_sci_paths",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        paths = await client._sci_paths_for_cache(year=2020)
    assert paths is None
    await client.close()
