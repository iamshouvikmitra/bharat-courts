"""Local mirror of the archive's parquet metadata shards.

Why: every ``ArchiveClient.search()`` currently re-fetches the same parquet
files from S3. Per shard that's ~16 KB–5 MB plus latency. For interactive use
or repeated queries against the same court/year, the second call should hit
disk and complete in milliseconds.

When: only when the query's partition can be **fully resolved** — i.e. both
``year`` (single or range) and ``court`` (single court for HC) are specified.
Open-ended queries (year=None, or HC with court=None) still go straight to
the S3 glob; caching every shard for every year would defeat itself.

TTL: 30 days by default (the SCI bucket updates bi-monthly, HC quarterly —
30 days is well inside both windows). Override via
``BHARAT_COURTS_ARCHIVE_METADATA_TTL_DAYS``.

Layout under cache root::

    metadata/
      sci/year=YYYY/metadata.parquet
      hc/year=YYYY/court=X_Y/bench=Z/metadata.parquet
      _listings/                    # cached S3 LIST results
        hc_courts_year=YYYY.json    # {"7_26": "delhi-id", ...}
        hc_benches_year=YYYY_court=X_Y.json   # ["bench1", "bench2", ...]
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

import httpx

from bharat_courts.archive.endpoints import HC_BUCKET, REGION, SCI_BUCKET
from bharat_courts.models import Court, CourtType

_log = logging.getLogger(__name__)

_DEFAULT_CACHE_ROOT = Path.home() / ".cache" / "bharat-courts" / "archive" / "metadata"
_DEFAULT_TTL_SECONDS = 30 * 86400  # 30 days

_LIST_NAMESPACE_RE = re.compile(r"<(?:Key|Prefix)>(.*?)</")


class _MetadataCache:
    """On-disk mirror of parquet metadata shards.

    Returns lists of local file paths that ``_ArchiveQuery`` can hand straight
    to ``read_parquet([…])``. Network I/O happens in the LISTing and the
    parquet download phases; both are TTL-checked.
    """

    def __init__(
        self,
        *,
        cache_dir: Path | str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        env_ttl = os.environ.get("BHARAT_COURTS_ARCHIVE_METADATA_TTL_DAYS")
        if ttl_seconds is None and env_ttl:
            try:
                ttl_seconds = int(float(env_ttl) * 86400)
            except ValueError:
                ttl_seconds = None
        self.cache_dir = Path(cache_dir or _DEFAULT_CACHE_ROOT)
        # NOTE: ``ttl_seconds or DEFAULT`` would silently override the legal
        # value 0 ("always stale") with the default, so be explicit.
        self.ttl_seconds = _DEFAULT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
        self._http: httpx.AsyncClient | None = None
        self._listing_locks: dict[str, asyncio.Lock] = {}
        self._download_locks: dict[str, asyncio.Lock] = {}

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=120.0),
                follow_redirects=True,
            )
        return self._http

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def get_sci_paths(self, year: int | tuple[int, int]) -> list[Path]:
        """Local parquet paths for the SCI shards covering the given year(s)."""
        years = self._expand_years(year)
        out: list[Path] = []
        for y in years:
            url = (
                f"https://{SCI_BUCKET}.s3.{REGION}.amazonaws.com"
                f"/metadata/parquet/year={y}/metadata.parquet"
            )
            local = self.cache_dir / "sci" / f"year={y}" / "metadata.parquet"
            if not await self._ensure_file(url, local):
                continue
            out.append(local)
        return out

    async def get_hc_paths(
        self,
        year: int | tuple[int, int],
        court: Court,
    ) -> list[Path]:
        """Local parquet paths for a (year-range, single HC) partition."""
        if court.court_type != CourtType.HIGH_COURT:
            raise ValueError("get_hc_paths requires a HIGH_COURT court")

        years = self._expand_years(year)
        out: list[Path] = []
        for y in years:
            # 1. Map state_code → archive_court_id (e.g. "26" → "7" for Delhi
            #    in 2020). This can drift year-over-year as the archive
            #    maintainer re-indexes, so we cache per-year.
            courts_by_state = await self._list_hc_courts_for_year(y)
            archive_court_id = courts_by_state.get(court.state_code)
            if archive_court_id is None:
                # This HC has no data for that year in the archive.
                continue
            court_partition = f"{archive_court_id}_{court.state_code}"

            # 2. List benches for that (year, court).
            benches = await self._list_hc_benches(y, court_partition)
            for bench in benches:
                url = (
                    f"https://{HC_BUCKET}.s3.{REGION}.amazonaws.com"
                    f"/metadata/parquet/year={y}/court={court_partition}"
                    f"/bench={bench}/metadata.parquet"
                )
                local = (
                    self.cache_dir
                    / "hc"
                    / f"year={y}"
                    / f"court={court_partition}"
                    / f"bench={bench}"
                    / "metadata.parquet"
                )
                if not await self._ensure_file(url, local):
                    continue
                out.append(local)
        return out

    def info(self) -> dict:
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
            "ttl_seconds": self.ttl_seconds,
        }

    # ------------------------------------------------------------------
    # internals — S3 listings (cached as JSON sidecars)
    # ------------------------------------------------------------------

    async def _list_hc_courts_for_year(self, year: int) -> dict[str, str]:
        """``{state_code: archive_court_id}`` for HC parquet partitions in a year."""
        path = self.cache_dir / "_listings" / f"hc_courts_year={year}.json"
        cached = self._read_json_if_fresh(path)
        if cached is not None:
            return cached

        url = (
            f"https://{HC_BUCKET}.s3.{REGION}.amazonaws.com/"
            f"?list-type=2&max-keys=200"
            f"&prefix=metadata/parquet/year={year}/&delimiter=/"
        )
        lock = self._listing_locks.setdefault(str(path), asyncio.Lock())
        async with lock:
            # Double-check after acquiring lock.
            cached = self._read_json_if_fresh(path)
            if cached is not None:
                return cached

            xml = (await self._client().get(url)).text
            # Extract "court=X_Y" prefixes.
            mapping: dict[str, str] = {}
            for match in _LIST_NAMESPACE_RE.finditer(xml):
                value = match.group(1)
                # path looks like: metadata/parquet/year=YYYY/court=X_Y/
                m = re.search(r"court=(\d+)_(\d+)/?$", value)
                if m:
                    archive_id, state_code = m.group(1), m.group(2)
                    mapping[state_code] = archive_id
            self._write_json(path, mapping)
            return mapping

    async def _list_hc_benches(self, year: int, court_partition: str) -> list[str]:
        """List bench slugs for a (year, court) partition."""
        safe = court_partition.replace("/", "_")
        path = self.cache_dir / "_listings" / f"hc_benches_year={year}_court={safe}.json"
        cached = self._read_json_if_fresh(path)
        if cached is not None:
            return cached

        url = (
            f"https://{HC_BUCKET}.s3.{REGION}.amazonaws.com/"
            f"?list-type=2&max-keys=200"
            f"&prefix=metadata/parquet/year={year}/court={court_partition}/&delimiter=/"
        )
        lock = self._listing_locks.setdefault(str(path), asyncio.Lock())
        async with lock:
            cached = self._read_json_if_fresh(path)
            if cached is not None:
                return cached

            xml = (await self._client().get(url)).text
            benches: list[str] = []
            for match in _LIST_NAMESPACE_RE.finditer(xml):
                value = match.group(1)
                m = re.search(r"bench=([^/]+)/?$", value)
                if m:
                    benches.append(m.group(1))
            self._write_json(path, benches)
            return benches

    # ------------------------------------------------------------------
    # internals — parquet file download + freshness
    # ------------------------------------------------------------------

    async def _ensure_file(self, url: str, local: Path) -> bool:
        """Make sure ``local`` is present and fresh; return False on 404."""
        if local.exists() and self._is_fresh(local):
            return True
        lock = self._download_locks.setdefault(str(local), asyncio.Lock())
        async with lock:
            if local.exists() and self._is_fresh(local):
                return True
            try:
                resp = await self._client().get(url)
                if resp.status_code == 404:
                    return False
                resp.raise_for_status()
            except httpx.HTTPError as e:
                _log.warning("metadata fetch failed %s: %s", url, e)
                return False
            await asyncio.to_thread(self._write_atomic, local, resp.content)
            return True

    def _is_fresh(self, path: Path) -> bool:
        try:
            age = time.time() - path.stat().st_mtime
        except FileNotFoundError:
            return False
        # mtime can be marginally in the future right after a write (clock
        # resolution + filesystem rounding). Clamp to non-negative so a TTL
        # of 0 reliably means "always stale" instead of "always fresh".
        return max(0.0, age) < self.ttl_seconds

    def _read_json_if_fresh(self, path: Path):
        if not path.exists() or not self._is_fresh(path):
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _write_json(self, path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_atomic(path, json.dumps(payload).encode())

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
    def _expand_years(year: int | tuple[int, int]) -> list[int]:
        if isinstance(year, tuple):
            lo, hi = year
            return list(range(int(lo), int(hi) + 1))
        return [int(year)]


__all__ = ["_MetadataCache"]
