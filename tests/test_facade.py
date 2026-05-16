"""Tests for the federated Judgments facade.

Routing rules + JudgmentResult→Judgment mapping are unit-tested with mocks;
no network. Live smoke lives in examples/, not in pytest.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest

from bharat_courts.facade import Judgments, live_to_judgment
from bharat_courts.models import Judgment, JudgmentResult, SearchResult

# ----- routing --------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs, expected",
    [
        # CNR present → archive, regardless of other filters
        (dict(source="auto", text=None, cnr="DLHC...", structured=False), "archive"),
        (dict(source="auto", text="bail", cnr="DLHC...", structured=True), "archive"),
        # Text only → live
        (dict(source="auto", text="right to privacy", cnr=None, structured=False), "live"),
        # Structured only → archive
        (dict(source="auto", text=None, cnr=None, structured=True), "archive"),
        # Text + structured → archive (text fallback to title-match)
        (dict(source="auto", text="bail", cnr=None, structured=True), "archive"),
        # Explicit override beats auto
        (dict(source="live", text=None, cnr="DLHC...", structured=False), "live"),
        (dict(source="archive", text="bail", cnr=None, structured=False), "archive"),
    ],
)
def test_resolve_source(kwargs, expected):
    assert Judgments._resolve_source(**kwargs) == expected


def test_resolve_source_no_filters_raises():
    with pytest.raises(ValueError, match="at least one"):
        Judgments._resolve_source(source="auto", text=None, cnr=None, structured=False)


# ----- JudgmentResult → Judgment mapping ------------------------------


def _make_live_result(**overrides):
    base = dict(
        title="ASIAN HOTELS v BEENA JAIN",
        court_name="Delhi High Court",
        case_number="RFA(OS)(COMM)/39/2020",
        judgment_date=date(2020, 12, 24),
        judges=["HON'BLE MR. JUSTICE RAJIV SAHAI ENDLAW"],
        pdf_url="court/cnrorders/dhcdb/orders/x.pdf",
        bench_type="Single Bench",
        source_id="DLHC010230802020",
        metadata={
            "disposal_nature": "Disposed off",
            "registration_date": "2020-08-25",
            "pdf_val": "0",
        },
    )
    base.update(overrides)
    return JudgmentResult(**base)


def test_live_to_judgment_preserves_core_fields():
    j = live_to_judgment(_make_live_result())
    assert j.cnr == "DLHC010230802020"
    assert j.title == "ASIAN HOTELS v BEENA JAIN"
    assert j.judges == ["HON'BLE MR. JUSTICE RAJIV SAHAI ENDLAW"]
    assert j.decision_date == date(2020, 12, 24)
    assert j.source == "live"
    assert j.year == 2020


def test_live_to_judgment_resolves_court_from_name():
    j = live_to_judgment(_make_live_result(court_name="Delhi High Court"))
    assert j.court is not None
    assert j.court.code == "delhi"


def test_live_to_judgment_keeps_raw_name_when_court_unknown():
    j = live_to_judgment(_make_live_result(court_name="Some Unknown Court"))
    assert j.court is None
    assert j.court_name_raw == "Some Unknown Court"


def test_live_to_judgment_propagates_metadata_disposal():
    j = live_to_judgment(_make_live_result())
    assert j.disposal_nature == "Disposed off"
    assert j.date_of_registration == date(2020, 8, 25)


def test_live_to_judgment_preserves_pdf_path():
    j = live_to_judgment(_make_live_result())
    assert j.pdf_path == "court/cnrorders/dhcdb/orders/x.pdf"


def test_live_to_judgment_handles_missing_optional_fields():
    jr = _make_live_result(
        judgment_date=None,
        judges=[],
        metadata={},
        source_id="",
        citation="",
    )
    j = live_to_judgment(jr)
    assert j.cnr is None
    assert j.decision_date is None
    assert j.disposal_nature is None
    assert j.year is None


# ----- find() dispatch --------------------------------------------------


@pytest.mark.asyncio
async def test_find_routes_text_to_live_path():
    """text-only query should hit the live backend and NOT touch archive."""
    facade = Judgments.__new__(Judgments)
    facade._archive = None
    facade._live = None

    live_called = {}

    async def fake_find_live(*, text, limit):
        live_called["text"] = text
        live_called["limit"] = limit
        return [live_to_judgment(_make_live_result())]

    async def archive_should_not_be_called(**kw):
        raise AssertionError("archive should not be called for text-only query")

    facade._find_live = fake_find_live
    facade._find_archive = archive_should_not_be_called

    results = await facade.find(text="privacy", limit=5)
    assert live_called == {"text": "privacy", "limit": 5}
    assert len(results) == 1
    assert results[0].source == "live"


@pytest.mark.asyncio
async def test_find_routes_structured_to_archive_path():
    facade = Judgments.__new__(Judgments)
    facade._archive = None
    facade._live = None

    archive_called = {}

    async def fake_find_archive(**kw):
        archive_called.update(kw)
        return [Judgment(cnr="ESCR010000301950", source="archive")]

    async def live_should_not_be_called(*a, **kw):
        raise AssertionError("live should not be called for structured-only query")

    facade._find_archive = fake_find_archive
    facade._find_live = live_should_not_be_called

    results = await facade.find(judge="chandrachud", year=2020, limit=10)
    assert archive_called["judge"] == "chandrachud"
    assert archive_called["year"] == 2020
    assert archive_called["limit"] == 10
    assert results[0].cnr == "ESCR010000301950"


@pytest.mark.asyncio
async def test_find_routes_cnr_to_archive():
    facade = Judgments.__new__(Judgments)
    facade._archive = None
    facade._live = None

    archive_seen = {}

    async def fake_find_archive(**kw):
        archive_seen.update(kw)
        return []

    async def live_no(*a, **kw):
        raise AssertionError("live should not be called for cnr query")

    facade._find_archive = fake_find_archive
    facade._find_live = live_no

    await facade.find(cnr="DLHC010230802020")
    assert archive_seen["cnr"] == "DLHC010230802020"


@pytest.mark.asyncio
async def test_find_mixed_text_plus_structured_uses_archive_with_party_fallback():
    """Mixed query: archive should be called with `party=text` so the title
    column gets searched alongside the structured filters."""
    facade = Judgments.__new__(Judgments)
    facade._archive = None
    facade._live = None

    # We unit-test the body of _find_archive directly by stubbing the archive.
    fake_archive = AsyncMock()
    fake_archive.search = AsyncMock(return_value=[])
    facade._archive = fake_archive
    # Bypass lazy init.

    async def get_archive():
        return fake_archive

    facade._get_archive = get_archive  # type: ignore[assignment]

    await facade.find(text="bank", court="delhi", year=2020)
    fake_archive.search.assert_awaited_once()
    call = fake_archive.search.await_args
    assert call.kwargs["party"] == "bank", "text= should be folded into party= for mixed queries"


@pytest.mark.asyncio
async def test_find_explicit_source_archive_for_text_raises_when_no_text_fallback():
    """source='archive' + text only (no structured) → archive called with party=text.

    The archive can't do full-body search, so this is a best-effort title match.
    Verify the call routes to archive (not live) and the SDK warns the user.
    """
    facade = Judgments.__new__(Judgments)
    facade._archive = None
    facade._live = None

    fake_archive = AsyncMock()
    fake_archive.search = AsyncMock(return_value=[])
    facade._archive = fake_archive

    async def get_archive():
        return fake_archive

    facade._get_archive = get_archive  # type: ignore[assignment]

    await facade.find(text="bail", source="archive", limit=5)
    # archive.search WAS called (live wasn't, by exclusion).
    fake_archive.search.assert_awaited_once()
    assert fake_archive.search.await_args.kwargs["party"] == "bail"


@pytest.mark.asyncio
async def test_find_explicit_source_live_without_text_raises():
    """Forcing source='live' with only a CNR fails loudly — live can't take CNRs.

    Don't stub _find_live: we want the real validation message.
    """
    facade = Judgments.__new__(Judgments)
    facade._archive = None
    facade._live = None
    with pytest.raises(ValueError, match="text"):
        await facade.find(cnr="DLHC010230802020", source="live")


@pytest.mark.asyncio
async def test_find_live_trims_to_limit():
    """Live's portal page_size is capped at 25; the facade must respect ``limit``."""
    facade = Judgments.__new__(Judgments)
    facade._archive = None
    facade._live = None

    fake_live = AsyncMock()
    sr = SearchResult(
        items=[_make_live_result(source_id=f"X{i}") for i in range(20)],
        total_count=20,
        page=1,
        page_size=25,
        has_next=False,
    )
    fake_live.search = AsyncMock(return_value=sr)

    async def get_live():
        return fake_live

    facade._get_live = get_live  # type: ignore[assignment]

    results = await facade.find(text="bail", limit=5)
    assert len(results) == 5
    assert all(r.source == "live" for r in results)


# ----- fetch_pdf --------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_pdf_live_judgment_raises_notimplemented():
    """Live PDFs need the original JudgmentResult; facade points users there."""
    facade = Judgments.__new__(Judgments)
    facade._archive = None
    facade._live = None
    j = live_to_judgment(_make_live_result())
    with pytest.raises(NotImplementedError, match="JudgmentSearchClient"):
        await facade.fetch_pdf(j)


@pytest.mark.asyncio
async def test_fetch_pdf_archive_judgment_routes_to_archive():
    facade = Judgments.__new__(Judgments)
    facade._archive = None
    facade._live = None

    fake_archive = AsyncMock()
    fake_archive.fetch_pdf = AsyncMock(return_value=b"%PDF-1.4 ...")

    async def get_archive():
        return fake_archive

    facade._get_archive = get_archive  # type: ignore[assignment]

    archive_j = Judgment(cnr="DLHC010230802020", source="archive")
    data = await facade.fetch_pdf(archive_j)
    assert data.startswith(b"%PDF")
    fake_archive.fetch_pdf.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_pdf_cnr_string_routes_to_archive():
    facade = Judgments.__new__(Judgments)
    facade._archive = None
    facade._live = None

    fake_archive = AsyncMock()
    fake_archive.fetch_pdf = AsyncMock(return_value=b"%PDF-1.4")

    async def get_archive():
        return fake_archive

    facade._get_archive = get_archive  # type: ignore[assignment]

    await facade.fetch_pdf("DLHC010230802020")
    fake_archive.fetch_pdf.assert_awaited_once_with("DLHC010230802020", language="english")
