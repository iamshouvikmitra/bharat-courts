"""Archive access — bulk historical judgments via AWS Open Data S3 buckets.

Two public buckets, both in ``ap-south-1`` under CC-BY-4.0:

- ``s3://indian-supreme-court-judgments/`` (1950–present, bi-monthly updates)
- ``s3://indian-high-court-judgments/`` (25 HCs, quarterly updates)

Phase 1 surface: read metadata only. The :class:`ArchiveClient` runs DuckDB
queries against the partitioned parquet metadata and returns
:class:`bharat_courts.models.Judgment` instances. PDF retrieval lands in Phase 2.

Requires the ``archive`` extra::

    pip install bharat-courts[archive]
"""

from bharat_courts.archive.client import ArchiveClient
from bharat_courts.archive.schema import row_to_judgment
from bharat_courts.archive.storage import ArchivePdfError

__all__ = ["ArchiveClient", "ArchivePdfError", "row_to_judgment"]
