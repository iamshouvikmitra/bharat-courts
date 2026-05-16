"""High-level archive facade.

Consumers see one method — :meth:`ArchiveClient.search` — that routes the
query to the right bucket(s) based on the ``court`` argument, normalises
both schemas through :func:`row_to_judgment`, and returns a list of
:class:`Judgment`.

Async on the outside (matching the rest of the SDK), sync DuckDB inside —
queries run via ``asyncio.to_thread`` so they don't block the event loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Self

from bharat_courts.archive.metadata import _ArchiveQuery
from bharat_courts.archive.metadata_cache import _MetadataCache
from bharat_courts.archive.schema import row_to_judgment
from bharat_courts.archive.storage import ArchivePdfError, _PdfStorage
from bharat_courts.courts import get_court, infer_court_from_cnr
from bharat_courts.models import Court, CourtType, Judgment


class ArchiveClient:
    """Query the public AWS Open Data judgment archives.

    Example::

        async with ArchiveClient() as client:
            results = await client.search(
                court="sci", judge="chandrachud", year=(2018, 2024), limit=20
            )
            for j in results:
                print(j.decision_date, j.title)
    """

    def __init__(
        self,
        *,
        cache_dir: str | None = None,
        cache_max_bytes: int | None = None,
        metadata_cache: bool = True,
    ) -> None:
        self._query = _ArchiveQuery()
        self._storage = _PdfStorage(cache_dir=cache_dir, max_bytes=cache_max_bytes)
        # Metadata cache mirrors parquet shards locally when the query's
        # partition is fully resolved. Disable for one-off scans where
        # caching is wasted.
        self._meta_cache: _MetadataCache | None = _MetadataCache() if metadata_cache else None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await asyncio.to_thread(self._query.close)
        await self._storage.aclose()
        if self._meta_cache is not None:
            await self._meta_cache.aclose()

    # ------------------------------------------------------------------
    # internal: decide whether to use the local parquet cache
    # ------------------------------------------------------------------

    async def _sci_paths_for_cache(
        self,
        year: int | tuple[int, int] | None,
    ) -> list | None:
        """Return cached SCI parquet paths, or None to fall back to the S3 glob."""
        if self._meta_cache is None or year is None:
            return None
        try:
            paths = await self._meta_cache.get_sci_paths(year)
        except Exception as e:  # don't let cache bugs break queries
            __import__("logging").getLogger(__name__).warning(
                "metadata cache miss (falling back to S3): %s", e
            )
            return None
        return paths or None

    async def _hc_paths_for_cache(
        self,
        court: Court | None,
        year: int | tuple[int, int] | None,
    ) -> list | None:
        """Return cached HC parquet paths, or None to fall back to the S3 glob.

        Requires both ``court`` (a specific HC) and ``year`` to be set —
        without both, we'd be caching too much for too little gain.
        """
        if self._meta_cache is None or year is None or court is None:
            return None
        if court.court_type != CourtType.HIGH_COURT:
            return None
        try:
            paths = await self._meta_cache.get_hc_paths(year, court)
        except Exception as e:
            __import__("logging").getLogger(__name__).warning(
                "metadata cache miss (falling back to S3): %s", e
            )
            return None
        return paths or None

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    async def search(
        self,
        *,
        court: Court | str | None = None,
        year: int | tuple[int, int] | None = None,
        judge: str | None = None,
        party: str | None = None,
        citation: str | None = None,
        cnr: str | None = None,
        limit: int = 50,
    ) -> list[Judgment]:
        """Search judgments in the archive.

        :param court:
            ``Court`` instance, a court code (``"sci"``, ``"delhi"``), or
            ``None`` to query both Supreme Court and all High Courts.
        :param year:
            Single year (``2020``) or inclusive range (``(2018, 2024)``).
            Year filters benefit from partition pruning and are strongly
            recommended for non-CNR queries.
        :param judge: Case-insensitive substring match on the judge field.
        :param party:
            Case-insensitive match. For SCI, searches petitioner, respondent,
            and title; for HC, searches title (HC parquet has no
            petitioner/respondent columns).
        :param citation: Case-insensitive substring match (SCI only — HC
            parquet has no citation column; filter is silently ignored.)
        :param cnr: Exact match on the CNR (Court Number Record). When ``court``
            isn't given, the CNR's 4-letter prefix is used to infer the right
            court and avoid scanning all 25 HC partitions.
        :param limit: Maximum results to return (split across sources if both
            queried).
        """
        resolved = self._resolve_court(court)
        # CNR-only queries: infer source from the prefix so we don't scan every
        # HC partition for an SCI CNR (or vice-versa).
        if resolved is None and cnr:
            resolved = infer_court_from_cnr(cnr)

        per_source_limit = limit if resolved is not None else max(1, limit // 2)
        results: list[Judgment] = []

        if resolved is None or resolved.court_type == CourtType.SUPREME_COURT:
            sci_paths = await self._sci_paths_for_cache(year)
            sci_rows = await asyncio.to_thread(
                self._query.search_sci,
                year=year,
                judge=judge,
                party=party,
                citation=citation,
                cnr=cnr,
                limit=per_source_limit,
                paths_override=sci_paths,
            )
            results.extend(row_to_judgment(r) for r in sci_rows)

        if resolved is None or resolved.court_type == CourtType.HIGH_COURT:
            hc_court = resolved if resolved else None
            hc_paths = await self._hc_paths_for_cache(hc_court, year)
            hc_rows = await asyncio.to_thread(
                self._query.search_hc,
                court=hc_court,
                year=year,
                judge=judge,
                party=party,
                cnr=cnr,
                limit=per_source_limit,
                paths_override=hc_paths,
            )
            results.extend(row_to_judgment(r) for r in hc_rows)

        # Sort merged results so the cross-source list is still date-ordered.
        results.sort(
            key=lambda j: j.decision_date or __import__("datetime").date.min,
            reverse=True,
        )
        return results[:limit]

    async def iter_judgments(
        self,
        *,
        court: Court | str | None = None,
        year: int | tuple[int, int] | None = None,
        judge: str | None = None,
        party: str | None = None,
        citation: str | None = None,
        cnr: str | None = None,
        batch_size: int = 500,
        max_results: int | None = None,
    ) -> AsyncIterator[Judgment]:
        """Stream judgments matching the filters, paging via ``LIMIT/OFFSET``.

        Use this instead of :meth:`search` for bulk pulls — e.g. "all Delhi
        2020 judgments" (~18k rows) — to avoid materialising everything in
        memory and to start consuming results immediately.

        Sources are streamed sequentially: SCI first (if applicable), then HC.
        There is **no** cross-source date merge — that would require holding
        both fully sorted lists. Each source is internally sorted by
        ``decision_date DESC, cnr`` so individual pages are deterministic.

        ``batch_size`` controls the SQL page size. ``max_results`` caps the
        total yielded count across sources; ``None`` means no cap.
        """
        resolved = self._resolve_court(court)
        if resolved is None and cnr:
            resolved = infer_court_from_cnr(cnr)

        yielded = 0
        sci_paths = await self._sci_paths_for_cache(year)
        hc_paths = await self._hc_paths_for_cache(resolved, year)

        async def _drain_source(source: str) -> AsyncIterator[Judgment]:
            nonlocal yielded
            offset = 0
            while True:
                if max_results is not None and yielded >= max_results:
                    return
                page_limit = batch_size
                if max_results is not None:
                    page_limit = min(batch_size, max_results - yielded)
                if source == "sci":
                    rows = await asyncio.to_thread(
                        self._query.search_sci,
                        year=year,
                        judge=judge,
                        party=party,
                        citation=citation,
                        cnr=cnr,
                        limit=page_limit,
                        offset=offset,
                        paths_override=sci_paths,
                    )
                else:  # hc
                    rows = await asyncio.to_thread(
                        self._query.search_hc,
                        court=resolved,
                        year=year,
                        judge=judge,
                        party=party,
                        cnr=cnr,
                        limit=page_limit,
                        offset=offset,
                        paths_override=hc_paths,
                    )
                if not rows:
                    return
                for r in rows:
                    yield row_to_judgment(r)
                    yielded += 1
                    if max_results is not None and yielded >= max_results:
                        return
                if len(rows) < page_limit:
                    return  # last page
                offset += len(rows)

        if resolved is None or resolved.court_type == CourtType.SUPREME_COURT:
            async for j in _drain_source("sci"):
                yield j

        if resolved is None or resolved.court_type == CourtType.HIGH_COURT:
            async for j in _drain_source("hc"):
                yield j

    # ------------------------------------------------------------------
    # PDF retrieval
    # ------------------------------------------------------------------

    async def fetch_pdf(
        self,
        judgment_or_cnr: Judgment | str,
        *,
        language: str = "english",
    ) -> bytes:
        """Fetch the PDF bytes for a judgment.

        Pass a :class:`Judgment` (preferred — no extra lookup) or a CNR string
        (triggers one metadata query first). The ``language`` argument is only
        meaningful for SCI judgments; HC has English-only PDFs in the archive.

        Raises :class:`ArchivePdfError` for missing files, missing metadata
        fields needed to construct the S3 path, or HTTP failures.
        """
        if isinstance(judgment_or_cnr, str):
            j = await self._lookup_by_cnr(judgment_or_cnr)
        else:
            j = judgment_or_cnr

        if j.court is None:
            raise ArchivePdfError(
                f"Judgment has no resolved court — cannot route PDF fetch (cnr={j.cnr})"
            )

        if j.court.court_type == CourtType.SUPREME_COURT:
            return await self._storage.fetch_sci_pdf(j, language=language)
        return await self._storage.fetch_hc_pdf(j)

    async def prefetch_sci_year(self, year: int, language: str = "english") -> str:
        """Pre-warm the SCI tar cache for a year. Returns the local path."""
        path = await self._storage.prefetch_sci_tar(year, language=language)
        return str(path)

    def cache_info(self) -> dict:
        """Snapshot of cache directory + total bytes + cap."""
        return self._storage.cache_info()

    async def _lookup_by_cnr(self, cnr: str) -> Judgment:
        results = await self.search(cnr=cnr, limit=2)
        if not results:
            raise ArchivePdfError(f"No archive record for CNR {cnr!r}")
        return results[0]

    async def count(
        self,
        *,
        court: Court | str | None = None,
        year: int | None = None,
    ) -> dict[str, int]:
        """Return per-source row counts. Useful for sizing and sanity checks."""
        resolved = self._resolve_court(court)
        out: dict[str, int] = {}

        if resolved is None or resolved.court_type == CourtType.SUPREME_COURT:
            out["sci"] = await asyncio.to_thread(self._query.count_sci, year=year)

        if resolved is None or resolved.court_type == CourtType.HIGH_COURT:
            out["hc"] = await asyncio.to_thread(self._query.count_hc, court=resolved, year=year)

        return out

    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_court(court: Court | str | None) -> Court | None:
        if court is None or isinstance(court, Court):
            return court
        resolved = get_court(court)
        if resolved is None:
            raise ValueError(f"Unknown court code: {court!r}. Use bharat_courts.list_all_courts().")
        return resolved
