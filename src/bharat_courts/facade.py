"""Federated judgment search — one entry point, picks the right backend.

End consumers usually want *a judgment matching some criteria* and don't care
whether it came from the live eCourts portal or the AWS archive. :class:`Judgments`
exposes one method, :meth:`find`, that takes any combination of filters and
routes to the right backend, returning a uniform :class:`Judgment` list.

Routing rules (``source="auto"`` mode):

================================================  ========================
filters                                            backend
================================================  ========================
``cnr=`` set                                       archive (CNR prefix routing)
``text=`` set, no structured filters               live (only it does full-text)
structured filters only (judge/party/year/…)       archive (faster, no CAPTCHA)
``text=`` + structured                             archive (text falls back to title match)
nothing                                            ``ValueError``
================================================  ========================

Use ``source="archive"`` or ``source="live"`` to force a specific backend.

Both backends are lazy-initialised — install only what you need:

* ``pip install 'bharat-courts[archive]'`` for archive (DuckDB)
* ``pip install 'bharat-courts[ocr]'`` for live (CAPTCHA solving)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from typing import Literal, Self

from bharat_courts.courts import get_court_by_name, infer_court_from_cnr
from bharat_courts.models import Court, Judgment, JudgmentResult

_log = logging.getLogger(__name__)


Source = Literal["auto", "archive", "live"]


def live_to_judgment(jr: JudgmentResult) -> Judgment:
    """Map a live :class:`JudgmentResult` to the unified :class:`Judgment`.

    Field mapping:

    ====================  ====================================================
    JudgmentResult         Judgment
    ====================  ====================================================
    ``title``              ``title``
    ``court_name``         ``court_name_raw``; resolved into ``court`` via
                           the courts registry if a match is found
    ``source_id``          ``cnr`` (the judgments portal uses CNR as its id)
    ``judges``             ``judges``
    ``judgment_date``      ``decision_date``
    ``citation``           ``citation`` (when non-empty)
    ``pdf_url``            ``pdf_path`` (raw path; live download needs the
                           original JudgmentResult, not just the path)
    ``metadata["disposal_nature"]``   ``disposal_nature``
    ``metadata["registration_date"]`` ``date_of_registration``
    ====================  ====================================================
    """
    court = get_court_by_name(jr.court_name) if jr.court_name else None
    reg_date = _parse_iso_date(jr.metadata.get("registration_date"))
    year = jr.judgment_date.year if jr.judgment_date else None
    return Judgment(
        cnr=jr.source_id or None,
        title=jr.title or None,
        court=court,
        court_name_raw=jr.court_name or "",
        judges=list(jr.judges),
        decision_date=jr.judgment_date,
        date_of_registration=reg_date,
        disposal_nature=jr.metadata.get("disposal_nature") or None,
        citation=jr.citation or None,
        pdf_path=jr.pdf_url or None,
        source="live",
        year=year,
    )


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


class Judgments:
    """Federated facade over :class:`ArchiveClient` and :class:`JudgmentSearchClient`.

    Example::

        async with Judgments() as j:
            # Free-text → live
            hits = await j.find(text="right to privacy", limit=10)

            # Structured → archive
            hits = await j.find(judge="chandrachud", year=2020, court="sci")

            # CNR → archive (auto-routed via prefix)
            hits = await j.find(cnr="DLHC010230802020")

            # Force a specific source
            hits = await j.find(text="bail", source="live", limit=5)

            # PDF fetch — handles archive judgments + CNR strings whose prefix
            # resolves to an archive-supported court.
            pdf = await j.fetch_pdf("DLHC010230802020")
    """

    def __init__(self) -> None:
        self._archive = None
        self._live = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._archive is not None:
            await self._archive.close()
            self._archive = None
        if self._live is not None:
            # JudgmentSearchClient is an async context manager — exit cleanly.
            await self._live.__aexit__(None, None, None)
            self._live = None

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def find(
        self,
        *,
        text: str | None = None,
        court: Court | str | None = None,
        year: int | tuple[int, int] | None = None,
        judge: str | None = None,
        party: str | None = None,
        citation: str | None = None,
        cnr: str | None = None,
        source: Source = "auto",
        limit: int = 50,
    ) -> list[Judgment]:
        """Find judgments. See module docstring for routing rules."""
        structured = any(x is not None for x in (court, year, judge, party, citation))
        backend = self._resolve_source(
            source=source,
            text=text,
            cnr=cnr,
            structured=structured,
        )
        _log.info("Judgments.find routing → %s", backend)

        if backend == "archive":
            return await self._find_archive(
                text=text,
                court=court,
                year=year,
                judge=judge,
                party=party,
                citation=citation,
                cnr=cnr,
                limit=limit,
            )
        return await self._find_live(text=text or "", limit=limit)

    async def fetch_pdf(
        self,
        judgment_or_cnr: Judgment | str,
        *,
        language: str = "english",
    ) -> bytes:
        """Fetch a judgment PDF.

        - Archive judgments and CNR strings whose prefix maps to a known
          court → :meth:`ArchiveClient.fetch_pdf`.
        - Live :class:`Judgment` objects → not supported here yet; use
          ``JudgmentSearchClient.download_pdf`` directly (it needs the
          original :class:`JudgmentResult` + ``court_type``).
        """
        if isinstance(judgment_or_cnr, Judgment) and judgment_or_cnr.source == "live":
            raise NotImplementedError(
                "PDFs for live judgments must be fetched via "
                "JudgmentSearchClient.download_pdf(judgment_result, court_type) — "
                "the live download needs the original JudgmentResult instance."
            )
        archive = await self._get_archive()
        return await archive.fetch_pdf(judgment_or_cnr, language=language)

    # ------------------------------------------------------------------
    # routing
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_source(
        *,
        source: Source,
        text: str | None,
        cnr: str | None,
        structured: bool,
    ) -> Literal["archive", "live"]:
        if source == "archive":
            return "archive"
        if source == "live":
            return "live"
        # auto
        if cnr:
            return "archive"
        if text and not structured:
            return "live"
        if structured:
            return "archive"
        raise ValueError(
            "find() needs at least one of text, cnr, or a structured filter "
            "(court / year / judge / party / citation)."
        )

    # ------------------------------------------------------------------
    # backends
    # ------------------------------------------------------------------

    async def _find_archive(
        self,
        *,
        text: str | None,
        court: Court | str | None,
        year: int | tuple[int, int] | None,
        judge: str | None,
        party: str | None,
        citation: str | None,
        cnr: str | None,
        limit: int,
    ) -> list[Judgment]:
        archive = await self._get_archive()
        # When the user combines ``text`` with structured filters, the archive
        # can't do full-body search, so we fold ``text`` into the ``party``
        # slot (which already matches against title + party columns).
        effective_party = party or text
        return await archive.search(
            court=court,
            year=year,
            judge=judge,
            party=effective_party,
            citation=citation,
            cnr=cnr,
            limit=limit,
        )

    async def _find_live(self, *, text: str, limit: int) -> list[Judgment]:
        if not text:
            raise ValueError(
                "Live source needs `text=` (the judgments portal only supports "
                "full-text search; structured filters aren't wired up yet)."
            )
        live = await self._get_live()
        # ``search`` returns a SearchResult of JudgmentResult. Map and trim.
        page_size = min(limit, 25)  # portal default; larger pages slower
        sr = await live.search(text, page=1, page_size=page_size)
        items = [live_to_judgment(jr) for jr in sr.items[:limit]]
        return items

    # ------------------------------------------------------------------
    # lazy client init
    # ------------------------------------------------------------------

    async def _get_archive(self):
        if self._archive is None:
            try:
                from bharat_courts.archive.client import ArchiveClient
            except ImportError as e:
                raise ImportError(
                    "Federated find() routed to archive but the [archive] extra "
                    "isn't installed. Run: pip install 'bharat-courts[archive]'."
                ) from e
            self._archive = ArchiveClient()
        return self._archive

    async def _get_live(self):
        if self._live is None:
            from bharat_courts.judgments.client import JudgmentSearchClient

            self._live = JudgmentSearchClient()
            # Async context-manager init — bypass `async with` so we can keep
            # the client open across calls within this facade's lifetime.
            await self._live.__aenter__()
        return self._live


__all__ = ["Judgments", "Source", "live_to_judgment"]

# Re-export to keep `from bharat_courts.facade import infer_court_from_cnr`
# convenient for users routing CNRs themselves.
_ = (infer_court_from_cnr, asyncio)  # avoid "unused import" complaints
