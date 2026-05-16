"""PDF storage layer for the archive client.

Two backing stores share one disk cache:

* **HC**: the bucket ships individual PDFs at
  ``data/pdf/year=Y/court=<X_Y>/bench=<slug>/<basename>``. We fetch one PDF per
  call (~250 KB), cache the bytes on disk, and serve subsequent hits from disk.

* **SCI**: the bucket only ships per-year tar bundles (``english.tar`` ~40–500 MB,
  ``regional.tar`` smaller). The first request for a (year, language) downloads
  the whole tar; later requests for any PDF in that year are served via
  :mod:`tarfile` random access against the cached tar.

Cache root defaults to ``~/.cache/bharat-courts/archive/``. Total size is
bounded by ``BHARAT_COURTS_ARCHIVE_CACHE_MAX_GB`` (default 5 GB) — when a
download would push us over the cap, the least-recently-accessed files are
evicted first. Eviction is mtime-based; reads ``os.utime``-touch the file so
"recently used" tracks actual access, not just initial download.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import httpx

from bharat_courts.archive.endpoints import (
    HC_BUCKET,
    HC_PDF_HTTPS,
    REGION,
    SCI_BUCKET,
    SCI_LANGUAGE_MAP,
    SCI_TAR_HTTPS,
)
from bharat_courts.models import Judgment

_log = logging.getLogger(__name__)

_DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "bharat-courts" / "archive"
_DEFAULT_MAX_BYTES = 5 * 1024**3  # 5 GiB
_TAR_DOWNLOAD_NOTIFY_THRESHOLD = 50 * 1024**2  # warn on stderr if >50 MB


class ArchivePdfError(RuntimeError):
    """Raised when a PDF cannot be located or fetched from the archive."""


class _PdfStorage:
    """Async PDF fetcher with on-disk LRU cache.

    One instance per :class:`ArchiveClient`. Thread-safety isn't a concern
    (single async event loop), but concurrent fetches of the same SCI tar
    are de-duplicated via a per-key lock so we never download a 200 MB file
    twice in parallel.
    """

    def __init__(
        self,
        *,
        cache_dir: Path | str | None = None,
        max_bytes: int | None = None,
    ) -> None:
        env_max = os.environ.get("BHARAT_COURTS_ARCHIVE_CACHE_MAX_GB")
        if max_bytes is None and env_max:
            try:
                max_bytes = int(float(env_max) * 1024**3)
            except ValueError:
                max_bytes = None
        self.cache_dir = Path(cache_dir or _DEFAULT_CACHE_ROOT)
        self.max_bytes = max_bytes or _DEFAULT_MAX_BYTES
        self._download_locks: dict[str, asyncio.Lock] = {}
        self._http: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _http_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, read=600.0),  # tars can take a while
                follow_redirects=True,
            )
        return self._http

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def fetch_hc_pdf(self, j: Judgment) -> bytes:
        """Fetch a single HC judgment PDF (one direct GET, cached on disk)."""
        if not (j.year and j.court_code and j.bench and j.pdf_path):
            missing = [
                k
                for k, v in (
                    ("year", j.year),
                    ("court_code", j.court_code),
                    ("bench", j.bench),
                    ("pdf_path", j.pdf_path),
                )
                if not v
            ]
            raise ArchivePdfError(
                f"HC PDF fetch needs year, court_code, bench, pdf_path — missing: {missing}"
            )
        # NOTE: we intentionally do NOT short-circuit on ``pdf_exists=False``.
        # The flag tracks whether the upstream eCourts portal claimed a PDF
        # was available at crawl time; the S3 bucket is populated separately
        # and often has PDFs the flag denies. Authoritative answer = S3 GET.

        url, cache_path = self._hc_target(j)

        # cache hit?
        cached = self._read_if_cached(cache_path)
        if cached is not None:
            return cached

        # download
        data = await self._download_bytes(url)
        if not data.startswith(b"%PDF"):
            raise ArchivePdfError(f"S3 returned non-PDF content for {url} (head={data[:32]!r})")
        await asyncio.to_thread(self._write_atomic, cache_path, data)
        await asyncio.to_thread(self._enforce_cap)
        return data

    async def fetch_sci_pdf(self, j: Judgment, language: str = "english") -> bytes:
        """Fetch one SCI judgment PDF, downloading the year tar on first use."""
        if not (j.year and j.pdf_path):
            raise ArchivePdfError("SCI PDF fetch needs year and pdf_path on the Judgment")

        lang_key = (language or "english").strip().lower()
        if lang_key not in SCI_LANGUAGE_MAP:
            raise ArchivePdfError(
                f"Unknown SCI language {language!r}. "
                f"Known: {sorted(set(v[1] for v in SCI_LANGUAGE_MAP.values()))}"
            )
        lang_dir, lang_suffix = SCI_LANGUAGE_MAP[lang_key]

        member_name = f"{j.pdf_path}_{lang_suffix}.pdf"
        tar_path = await self._ensure_sci_tar(j.year, lang_dir)

        try:
            data = await asyncio.to_thread(self._extract_member, tar_path, member_name)
        except KeyError as e:
            raise ArchivePdfError(
                f"PDF {member_name!r} not found in {lang_dir} tar for year {j.year}"
            ) from e

        # Touch the tar so it stays warm in LRU.
        await asyncio.to_thread(os.utime, tar_path, None)
        return data

    async def prefetch_sci_tar(self, year: int, language: str = "english") -> Path:
        """Download a SCI year tar (no extraction). Useful for bulk pre-warming."""
        lang_key = (language or "english").strip().lower()
        if lang_key not in SCI_LANGUAGE_MAP:
            raise ArchivePdfError(f"Unknown SCI language {language!r}")
        lang_dir, _ = SCI_LANGUAGE_MAP[lang_key]
        return await self._ensure_sci_tar(year, lang_dir)

    def cache_info(self) -> dict[str, Any]:
        """Stats useful for ``archive cache`` reporting and tests."""
        total = 0
        files = 0
        if self.cache_dir.exists():
            for p in self.cache_dir.rglob("*"):
                if p.is_file():
                    total += p.stat().st_size
                    files += 1
        return {
            "cache_dir": str(self.cache_dir),
            "files": files,
            "bytes": total,
            "max_bytes": self.max_bytes,
        }

    # ------------------------------------------------------------------
    # internals — path construction
    # ------------------------------------------------------------------

    def _hc_target(self, j: Judgment) -> tuple[str, Path]:
        """(url, local_cache_path) for an HC judgment."""
        court_partition = j.court_code.replace("~", "_")  # "7~26" → "7_26"
        basename = j.pdf_path.rsplit("/", 1)[-1]
        url = HC_PDF_HTTPS.format(
            year=j.year,
            court_partition=court_partition,
            bench=j.bench,
            basename=basename,
        )
        rel = (
            Path(HC_BUCKET)
            / "pdf"
            / f"year={j.year}"
            / f"court={court_partition}"
            / f"bench={j.bench}"
            / basename
        )
        return url, self.cache_dir / rel

    def _sci_tar_target(self, year: int, lang_dir: str) -> tuple[str, Path]:
        url = SCI_TAR_HTTPS.format(year=year, lang_dir=lang_dir)
        rel = Path(SCI_BUCKET) / "tar" / f"year={year}" / f"{lang_dir}.tar"
        return url, self.cache_dir / rel

    # ------------------------------------------------------------------
    # internals — downloads
    # ------------------------------------------------------------------

    async def _ensure_sci_tar(self, year: int, lang_dir: str) -> Path:
        url, path = self._sci_tar_target(year, lang_dir)
        if path.exists() and path.stat().st_size > 0:
            return path

        # De-dup concurrent downloads of the same tar.
        key = str(path)
        lock = self._download_locks.setdefault(key, asyncio.Lock())
        async with lock:
            if path.exists() and path.stat().st_size > 0:
                return path
            await self._download_stream(url, path, notify=True)

        await asyncio.to_thread(self._enforce_cap)
        return path

    async def _download_bytes(self, url: str) -> bytes:
        client = self._http_client()
        resp = await client.get(url)
        if resp.status_code == 404:
            raise ArchivePdfError(f"Not found in archive bucket: {url}")
        resp.raise_for_status()
        return resp.content

    async def _download_stream(self, url: str, dest: Path, *, notify: bool) -> None:
        """Stream a (potentially large) file to disk via a temp file + rename."""
        client = self._http_client()
        async with client.stream("GET", url) as resp:
            if resp.status_code == 404:
                raise ArchivePdfError(f"Not found in archive bucket: {url}")
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", "0") or 0)
            if notify and total >= _TAR_DOWNLOAD_NOTIFY_THRESHOLD:
                mb = total / (1024 * 1024)
                print(
                    f"[bharat-courts] downloading archive bundle ({mb:.0f} MB) to {dest}",
                    file=sys.stderr,
                )

            dest.parent.mkdir(parents=True, exist_ok=True)
            # mkstemp in the same dir gives us atomic-rename onto ``dest``
            # without crossing filesystems.
            fd, tmp_path = tempfile.mkstemp(prefix=".dl_", suffix=".part", dir=str(dest.parent))
            try:
                with os.fdopen(fd, "wb") as f:
                    # Each chunk write is sync but tiny relative to the async
                    # network read; the event loop only blocks briefly between
                    # network reads.
                    async for chunk in resp.aiter_bytes(chunk_size=1024 * 1024):
                        f.write(chunk)
                os.replace(tmp_path, dest)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

    # ------------------------------------------------------------------
    # internals — disk I/O
    # ------------------------------------------------------------------

    def _read_if_cached(self, path: Path) -> bytes | None:
        if not path.exists():
            return None
        try:
            os.utime(path, None)  # touch for LRU
            return path.read_bytes()
        except OSError:
            return None

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".w_", suffix=".part", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _extract_member(tar_path: Path, member_name: str) -> bytes:
        with tarfile.open(tar_path, "r") as t:
            member = t.getmember(member_name)  # raises KeyError if absent
            fp = t.extractfile(member)
            if fp is None:
                raise KeyError(member_name)
            return fp.read()

    # ------------------------------------------------------------------
    # internals — LRU eviction
    # ------------------------------------------------------------------

    def _enforce_cap(self) -> None:
        if not self.cache_dir.exists():
            return
        files: list[tuple[float, int, Path]] = []
        total = 0
        for p in self.cache_dir.rglob("*"):
            if p.is_file():
                try:
                    st = p.stat()
                except FileNotFoundError:
                    continue
                files.append((st.st_mtime, st.st_size, p))
                total += st.st_size

        if total <= self.max_bytes:
            return

        # Evict oldest first.
        files.sort(key=lambda t: t[0])
        for mtime, size, path in files:
            if total <= self.max_bytes:
                break
            try:
                path.unlink()
                total -= size
                _log.info("evicted %s (%d bytes)", path, size)
            except OSError:
                continue


__all__ = ["_PdfStorage", "ArchivePdfError"]
# REGION re-export keeps mypy quiet about the unused import (template strings use it).
_ = REGION
