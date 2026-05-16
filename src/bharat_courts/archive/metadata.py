"""DuckDB-backed query layer over the partitioned parquet metadata.

The two buckets have different schemas, so we build and execute two
parameterised SQL queries — one per bucket — and merge results in Python.

DuckDB's ``hive_partitioning=true`` enables partition pruning: filters on
``year`` and ``court`` (the partition columns) only fetch matching parquet
shards. A year+court filter against an HC bench typically completes in
1–3 seconds against the public bucket.

Anonymous reads are configured via an empty S3 secret — DuckDB then skips
its credential discovery chain and uses unauthenticated requests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bharat_courts.archive.endpoints import (
    HC_METADATA_GLOB,
    REGION,
    SCI_METADATA_GLOB,
)
from bharat_courts.models import Court, CourtType


def _from_clause(default_glob: str, paths_override: list[Path] | None) -> str:
    """Build the ``FROM read_parquet(...)`` source for a query."""
    if paths_override:
        # DuckDB accepts an explicit list of paths. Use forward slashes for
        # cross-platform safety and quote each entry.
        listed = ",".join(f"'{p.as_posix()}'" for p in paths_override)
        return f"read_parquet([{listed}], hive_partitioning=true)"
    return f"read_parquet('{default_glob}', hive_partitioning=true)"


class _ArchiveQuery:
    """Holds a connected DuckDB instance and exposes typed search methods."""

    def __init__(self) -> None:
        try:
            import duckdb  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "Archive access requires duckdb. Install with: pip install 'bharat-courts[archive]'"
            ) from e
        self._con: Any | None = None

    def _connect(self) -> Any:
        if self._con is None:
            import duckdb

            con = duckdb.connect()
            con.execute("INSTALL httpfs;")
            con.execute("LOAD httpfs;")
            con.execute(
                f"CREATE OR REPLACE SECRET (TYPE S3, REGION '{REGION}', KEY_ID '', SECRET '');"
            )
            # The default TTY progress bar swamps non-interactive output and
            # is hostile to JSON/log piping. Users wanting a progress bar can
            # re-enable it via PRAGMA on the returned connection.
            con.execute("PRAGMA disable_progress_bar;")
            self._con = con
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    # ------------------------------------------------------------------
    # SCI query
    # ------------------------------------------------------------------

    def search_sci(
        self,
        *,
        year: int | tuple[int, int] | None = None,
        judge: str | None = None,
        party: str | None = None,
        citation: str | None = None,
        cnr: str | None = None,
        limit: int = 50,
        offset: int = 0,
        paths_override: list[Path] | None = None,
    ) -> list[dict[str, Any]]:
        sql, params = self._build_sci_query(
            year=year,
            judge=judge,
            party=party,
            citation=citation,
            cnr=cnr,
            limit=limit,
            offset=offset,
            paths_override=paths_override,
        )
        return self._fetch_dicts(sql, params)

    def _build_sci_query(
        self,
        *,
        year: int | tuple[int, int] | None,
        judge: str | None,
        party: str | None,
        citation: str | None,
        cnr: str | None,
        limit: int,
        offset: int = 0,
        paths_override: list[Path] | None = None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if isinstance(year, tuple):
            clauses.append("CAST(year AS INTEGER) BETWEEN ? AND ?")
            params.extend([year[0], year[1]])
        elif year is not None:
            clauses.append("year = ?")
            params.append(str(year))

        if judge:
            clauses.append("judge ILIKE ?")
            params.append(f"%{judge}%")

        if party:
            clauses.append("(petitioner ILIKE ? OR respondent ILIKE ? OR title ILIKE ?)")
            pattern = f"%{party}%"
            params.extend([pattern, pattern, pattern])

        if citation:
            clauses.append("citation ILIKE ?")
            params.append(f"%{citation}%")

        if cnr:
            clauses.append("cnr = ?")
            params.append(cnr)

        where = " AND ".join(clauses) if clauses else "TRUE"
        from_clause = _from_clause(SCI_METADATA_GLOB, paths_override)
        # NB: ORDER BY ... LIMIT/OFFSET requires a stable sort to give
        # consistent pagination. ``decision_date`` is not unique, so we add
        # ``cnr`` as the tiebreaker — guarantees deterministic page boundaries.
        sql = f"""
            SELECT cnr, case_id, title, petitioner, respondent, description,
                   judge, author_judge, citation, decision_date, disposal_nature,
                   court, available_languages, path, year
            FROM {from_clause}
            WHERE {where}
            ORDER BY decision_date DESC NULLS LAST, cnr
            LIMIT {int(limit)} OFFSET {int(offset)}
        """
        return sql, params

    # ------------------------------------------------------------------
    # HC query
    # ------------------------------------------------------------------

    def search_hc(
        self,
        *,
        court: Court | None = None,
        year: int | tuple[int, int] | None = None,
        judge: str | None = None,
        party: str | None = None,
        cnr: str | None = None,
        limit: int = 50,
        offset: int = 0,
        paths_override: list[Path] | None = None,
    ) -> list[dict[str, Any]]:
        sql, params = self._build_hc_query(
            court=court,
            year=year,
            judge=judge,
            party=party,
            cnr=cnr,
            limit=limit,
            offset=offset,
            paths_override=paths_override,
        )
        return self._fetch_dicts(sql, params)

    def _build_hc_query(
        self,
        *,
        court: Court | None,
        year: int | tuple[int, int] | None,
        judge: str | None,
        party: str | None,
        cnr: str | None,
        limit: int,
        offset: int = 0,
        paths_override: list[Path] | None = None,
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        if court is not None and court.court_type == CourtType.HIGH_COURT:
            # Partition column ``court`` is "<archive_id>_<state_code>".
            # Filter on the trailing state_code for partition pruning.
            clauses.append("SPLIT_PART(court, '_', 2) = ?")
            params.append(court.state_code)

        if isinstance(year, tuple):
            clauses.append("CAST(year AS INTEGER) BETWEEN ? AND ?")
            params.extend([year[0], year[1]])
        elif year is not None:
            clauses.append("year = ?")
            params.append(str(year))

        if judge:
            clauses.append("judge ILIKE ?")
            params.append(f"%{judge}%")

        if party:
            # HC parquet doesn't have petitioner/respondent columns —
            # parties are encoded in the title.
            clauses.append("title ILIKE ?")
            params.append(f"%{party}%")

        if cnr:
            clauses.append("cnr = ?")
            params.append(cnr)

        where = " AND ".join(clauses) if clauses else "TRUE"
        # NOTE: do not project the ``court`` column. With ``hive_partitioning=true``
        # DuckDB overrides the parquet's ``court`` column with the partition value
        # (e.g. "7_26"), shadowing the friendly name. The resolved bharat-courts
        # ``Court`` carries the canonical name; ``court_code`` ("X~Y") is enough
        # to drive that resolution.
        from_clause = _from_clause(HC_METADATA_GLOB, paths_override)
        sql = f"""
            SELECT cnr, court_code, title, description, judge,
                   date_of_registration, decision_date, disposal_nature,
                   pdf_link, pdf_exists, year, bench
            FROM {from_clause}
            WHERE {where}
            ORDER BY decision_date DESC NULLS LAST, cnr
            LIMIT {int(limit)} OFFSET {int(offset)}
        """
        return sql, params

    # ------------------------------------------------------------------
    # Aggregate helpers
    # ------------------------------------------------------------------

    def count_sci(self, *, year: int | None = None) -> int:
        where = "year = ?" if year is not None else "TRUE"
        params = [str(year)] if year is not None else []
        sql = (
            f"SELECT COUNT(*) FROM read_parquet('{SCI_METADATA_GLOB}', "
            f"hive_partitioning=true) WHERE {where}"
        )
        return int(self._fetch_one(sql, params)[0])

    def count_hc(self, *, court: Court | None = None, year: int | None = None) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if court is not None and court.court_type == CourtType.HIGH_COURT:
            clauses.append("SPLIT_PART(court, '_', 2) = ?")
            params.append(court.state_code)
        if year is not None:
            clauses.append("year = ?")
            params.append(str(year))
        where = " AND ".join(clauses) if clauses else "TRUE"
        sql = (
            f"SELECT COUNT(*) FROM read_parquet('{HC_METADATA_GLOB}', "
            f"hive_partitioning=true) WHERE {where}"
        )
        return int(self._fetch_one(sql, params)[0])

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fetch_dicts(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        con = self._connect()
        cursor = con.execute(sql, params)
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row, strict=True)) for row in cursor.fetchall()]

    def _fetch_one(self, sql: str, params: list[Any]) -> tuple:
        con = self._connect()
        return con.execute(sql, params).fetchone()
