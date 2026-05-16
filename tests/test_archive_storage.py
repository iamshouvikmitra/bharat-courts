"""Tests for the archive PDF storage layer.

Strategy: build a tiny synthetic tar on disk and exercise the extraction +
cache code paths without touching S3. HTTP downloads are mocked via respx.
"""

from __future__ import annotations

import io
import tarfile
import time
from pathlib import Path

import httpx
import pytest
import respx

from bharat_courts.archive.storage import ArchivePdfError, _PdfStorage
from bharat_courts.courts import SUPREME_COURT, get_court_by_state_code
from bharat_courts.models import Judgment

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_tar(members: dict[str, bytes]) -> bytes:
    """Build an in-memory tar with ``members[name] = content``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _fake_pdf(payload: bytes = b"") -> bytes:
    return b"%PDF-1.4\n" + payload + b"\n%%EOF\n"


def _hc_judgment(**overrides) -> Judgment:
    base = dict(
        cnr="DLHC010230802020",
        title="ASIAN HOTELS v BEENA JAIN",
        court=get_court_by_state_code("26"),
        bench="dhcdb",
        court_code="7~26",
        year=2020,
        pdf_path="court/cnrorders/dhcdb/orders/DLHC010230802020_1_2020-12-24.pdf",
        pdf_exists=True,
        source="archive",
    )
    base.update(overrides)
    return Judgment(**base)


def _sci_judgment(**overrides) -> Judgment:
    base = dict(
        cnr="ESCR010000301950",
        case_id="1950 INSC 25",
        title="SRI RANGA NILAYAM",
        court=SUPREME_COURT,
        year=1950,
        pdf_path="1950_1_806_821",
        available_languages=["eng"],
        source="archive",
    )
    base.update(overrides)
    return Judgment(**base)


# ---------------------------------------------------------------------------
# tar extraction (no network)
# ---------------------------------------------------------------------------


def test_extract_member_returns_bytes(tmp_path: Path):
    tar = tmp_path / "english.tar"
    tar.write_bytes(_make_tar({"1950_1_806_821_EN.pdf": _fake_pdf(b"hello")}))
    data = _PdfStorage._extract_member(tar, "1950_1_806_821_EN.pdf")
    assert data.startswith(b"%PDF")
    assert b"hello" in data


def test_extract_member_missing_raises_keyerror(tmp_path: Path):
    tar = tmp_path / "english.tar"
    tar.write_bytes(_make_tar({"other.pdf": _fake_pdf()}))
    with pytest.raises(KeyError):
        _PdfStorage._extract_member(tar, "missing.pdf")


# ---------------------------------------------------------------------------
# path construction
# ---------------------------------------------------------------------------


def test_hc_target_constructs_correct_url_and_path(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _hc_judgment()
    url, path = storage._hc_target(j)
    assert "data/pdf/year=2020/court=7_26/bench=dhcdb/DLHC010230802020_1_2020-12-24.pdf" in url
    # Cache path mirrors the S3 path under the bucket dir.
    assert path.name == "DLHC010230802020_1_2020-12-24.pdf"
    assert "court=7_26" in str(path)
    assert "bench=dhcdb" in str(path)


def test_sci_tar_target_picks_correct_language_dir(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    url, path = storage._sci_tar_target(2020, "english")
    assert "year=2020/english/english.tar" in url
    assert path.name == "english.tar"


# ---------------------------------------------------------------------------
# HC fetch — mocked HTTP
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_hc_pdf_caches_to_disk(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _hc_judgment()
    url, cache_path = storage._hc_target(j)

    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, content=_fake_pdf(b"hc")))
        data = await storage.fetch_hc_pdf(j)

    assert data.startswith(b"%PDF")
    assert cache_path.exists()
    assert cache_path.read_bytes() == data
    await storage.aclose()


@pytest.mark.asyncio
async def test_fetch_hc_pdf_uses_cache_on_second_call(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _hc_judgment()
    url, cache_path = storage._hc_target(j)

    with respx.mock:
        route = respx.get(url).mock(return_value=httpx.Response(200, content=_fake_pdf(b"hc")))
        first = await storage.fetch_hc_pdf(j)
        second = await storage.fetch_hc_pdf(j)
        # Only one HTTP call — second was served from disk.
        assert route.call_count == 1
        assert first == second

    await storage.aclose()


@pytest.mark.asyncio
async def test_fetch_hc_pdf_404_raises_archive_error(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _hc_judgment()
    url, _ = storage._hc_target(j)

    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(404, content=b"<Error/>"))
        with pytest.raises(ArchivePdfError, match="Not found"):
            await storage.fetch_hc_pdf(j)
    await storage.aclose()


@pytest.mark.asyncio
async def test_fetch_hc_pdf_non_pdf_response_raises(tmp_path: Path):
    """A 200 OK whose body isn't a PDF (e.g. an XML error inside HTML) must fail loudly."""
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _hc_judgment()
    url, cache_path = storage._hc_target(j)

    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, content=b"<html>oops</html>"))
        with pytest.raises(ArchivePdfError, match="non-PDF"):
            await storage.fetch_hc_pdf(j)

    assert not cache_path.exists(), "must not cache garbage bytes"
    await storage.aclose()


@pytest.mark.asyncio
async def test_fetch_hc_pdf_ignores_pdf_exists_false_flag(tmp_path: Path):
    """The parquet flag is unreliable — bucket reality wins. (Live verified.)"""
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _hc_judgment(pdf_exists=False)
    url, _ = storage._hc_target(j)

    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, content=_fake_pdf(b"ok")))
        data = await storage.fetch_hc_pdf(j)

    assert data.startswith(b"%PDF")
    await storage.aclose()


@pytest.mark.asyncio
async def test_fetch_hc_pdf_missing_metadata_raises(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _hc_judgment(bench=None, pdf_path=None)
    with pytest.raises(ArchivePdfError, match="bench"):
        await storage.fetch_hc_pdf(j)
    await storage.aclose()


# ---------------------------------------------------------------------------
# SCI fetch — mocked HTTP (stream a synthetic tar)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_sci_pdf_downloads_tar_and_extracts(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _sci_judgment()
    url, tar_path = storage._sci_tar_target(1950, "english")
    tar_bytes = _make_tar({"1950_1_806_821_EN.pdf": _fake_pdf(b"sci-judgment")})

    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, content=tar_bytes))
        data = await storage.fetch_sci_pdf(j, language="english")

    assert data.startswith(b"%PDF")
    assert b"sci-judgment" in data
    assert tar_path.exists()
    assert tar_path.read_bytes() == tar_bytes
    await storage.aclose()


@pytest.mark.asyncio
async def test_fetch_sci_pdf_skips_redownload_when_tar_exists(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _sci_judgment()
    url, tar_path = storage._sci_tar_target(1950, "english")
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    tar_path.write_bytes(_make_tar({"1950_1_806_821_EN.pdf": _fake_pdf(b"cached")}))

    with respx.mock:
        route = respx.get(url).mock(return_value=httpx.Response(500))
        data = await storage.fetch_sci_pdf(j, language="english")

    assert b"cached" in data
    assert route.call_count == 0
    await storage.aclose()


@pytest.mark.asyncio
async def test_fetch_sci_pdf_missing_member_raises(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _sci_judgment()
    url, _ = storage._sci_tar_target(1950, "english")
    # Tar exists but doesn't contain our PDF.
    with respx.mock:
        respx.get(url).mock(
            return_value=httpx.Response(200, content=_make_tar({"other.pdf": _fake_pdf()}))
        )
        with pytest.raises(ArchivePdfError, match="not found"):
            await storage.fetch_sci_pdf(j, language="english")
    await storage.aclose()


@pytest.mark.asyncio
async def test_fetch_sci_pdf_regional_language_maps_to_regional_tar(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _sci_judgment()
    # "hindi" should resolve to regional/HIN
    url, _ = storage._sci_tar_target(1950, "regional")
    tar_bytes = _make_tar({"1950_1_806_821_HIN.pdf": _fake_pdf(b"hindi")})

    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, content=tar_bytes))
        data = await storage.fetch_sci_pdf(j, language="hindi")

    assert b"hindi" in data
    await storage.aclose()


@pytest.mark.asyncio
async def test_fetch_sci_pdf_unknown_language_raises(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path)
    j = _sci_judgment()
    with pytest.raises(ArchivePdfError, match="Unknown SCI language"):
        await storage.fetch_sci_pdf(j, language="klingon")
    await storage.aclose()


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------


def test_enforce_cap_evicts_oldest_first(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path, max_bytes=100)
    # Three 60-byte files, total 180 > 100. After eviction, only the newest fits.
    files = []
    for i, name in enumerate(("old.pdf", "mid.pdf", "new.pdf")):
        p = tmp_path / "sub" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 60)
        # Stagger mtimes a full second apart so the OS doesn't conflate them.
        ts = time.time() + i
        import os as _os

        _os.utime(p, (ts, ts))
        files.append(p)

    storage._enforce_cap()
    # Only the newest should remain; oldest evicted first until under cap.
    assert not files[0].exists(), "oldest should be evicted"
    assert files[2].exists(), "newest should survive"


def test_cache_info_reports_totals(tmp_path: Path):
    storage = _PdfStorage(cache_dir=tmp_path, max_bytes=999)
    (tmp_path / "a.pdf").write_bytes(b"x" * 100)
    (tmp_path / "b.pdf").write_bytes(b"y" * 200)
    info = storage.cache_info()
    assert info["files"] == 2
    assert info["bytes"] == 300
    assert info["max_bytes"] == 999
    assert info["cache_dir"] == str(tmp_path)
