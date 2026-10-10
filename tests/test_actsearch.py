"""Tests for ActSearch: resolution, fan-out, de-duplication, partial failure.

The High Court client is replaced by a fake serving real captured act lists
and canned search rows, so these exercise the orchestration without touching
the portal.
"""

from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from bharat_courts.actsearch import ActSearch
from bharat_courts.courts import list_high_courts
from bharat_courts.hcservices.parser import CaptchaError, parse_code_name_list
from bharat_courts.models import CaseInfo, Judgment, SearchResult

ACT_LISTS = Path(__file__).parent / "fixtures" / "acts"

DELHI_ACTS = parse_code_name_list((ACT_LISTS / "delhi_hc.txt").read_text(encoding="utf-8"))
ALLAHABAD_ACTS = parse_code_name_list(
    (ACT_LISTS / "allahabad_hc_excerpt.txt").read_text(encoding="utf-8")
)


def _case(cnr: str, status: str = "Pending", decided: date | None = None) -> CaseInfo:
    return CaseInfo(
        case_number=f"{cnr[-6:-4]}/2024",
        case_type="CRL.M.C.",
        cnr_number=cnr,
        status=status,
        decision_date=decided,
    )


class FakeHC:
    """Stands in for HCServicesClient; records every call."""

    def __init__(self, acts_by_state, rows_by_code=None, *, fail_codes=(), benches=None):
        self.acts_by_state = acts_by_state
        self.rows_by_code = rows_by_code or {}
        self.fail_codes = set(fail_codes)
        self.benches = benches or {"1": "Principal Bench"}
        self.list_calls: list[tuple[str, str]] = []
        self.search_calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def list_acts(self, court, *, bench_code="1", search=""):
        self.list_calls.append((court.state_code, bench_code))
        acts = self.acts_by_state[court.state_code]
        if isinstance(acts, Exception):
            raise acts
        return acts

    async def list_benches(self, court):
        return self.benches

    async def case_status_by_act(
        self, court, *, act_code, section, status_filter, bench_code, year
    ):
        self.search_calls.append(
            dict(
                state=court.state_code,
                act_code=act_code,
                section=section,
                status=status_filter,
                bench=bench_code,
                year=year,
            )
        )
        if act_code in self.fail_codes:
            raise CaptchaError("CAPTCHA failed after 5 attempts")
        return [CaseInfo(**vars(c)) for c in self.rows_by_code.get(act_code, [])]


@pytest.fixture
def search(tmp_path):
    return ActSearch(captcha_solver=AsyncMock(), cache_dir=str(tmp_path))


def _use(search: ActSearch, fake: FakeHC) -> FakeHC:
    search._hc_client = lambda: fake  # type: ignore[method-assign]
    return fake


# ------------------------------------------------------------------
# Fan-out and de-duplication
# ------------------------------------------------------------------


async def test_searches_every_code_the_act_resolves_to(search):
    """Delhi files 1996-Act arbitrations under three codes: all three are searched."""
    fake = _use(search, FakeHC({"26": DELHI_ACTS}))

    result = await search.cases(act="arbitration", courts="delhi", status="Both")

    assert {c["act_code"] for c in fake.search_calls} == {"227", "165", "202"}
    assert all(c["status"] == "Both" for c in fake.search_calls)
    assert {m.code for m in result.resolution["delhi"]} == {"227", "165", "202"}
    assert result.errors == {}


async def test_hits_are_tagged_and_deduped_across_codes(search):
    rows = {
        "227": [_case("DLHC010000012024"), _case("DLHC010000022024")],
        "165": [_case("DLHC010000012024")],  # same case under a second code
    }
    _use(search, FakeHC({"26": DELHI_ACTS}, rows))

    result = await search.cases(act="arbitration", courts=["delhi"])

    cnrs = [h.case.cnr_number for h in result.hits]
    assert sorted(cnrs) == ["DLHC010000012024", "DLHC010000022024"]
    hit = result.hits[0]
    assert hit.court.code == "delhi"
    assert hit.act_key == "arbitration"
    assert hit.act_name in DELHI_ACTS.values()
    assert result.cases == [h.case for h in result.hits]


async def test_sections_are_searched_separately(search):
    fake = _use(search, FakeHC({"26": DELHI_ACTS}))

    await search.cases(act="IPC", courts="delhi", section=["302", "34"], year=(2020, 2024))

    assert [(c["act_code"], c["section"]) for c in fake.search_calls] == [
        ("1", "302"),
        ("1", "34"),
    ]
    assert fake.search_calls[0]["year"] == (2020, 2024)


async def test_include_successor_also_searches_the_new_code(search):
    """IPC 302 became BNS 103(1); the portal's section box takes the base, 103."""
    acts = {"1": "INDIAN PENAL CODE", "2": "BHARATIYA NYAYA SANHITA"}
    fake = _use(search, FakeHC({"17": acts}))

    result = await search.cases(act="IPC", courts="gujarat", section="302", include_successor=True)

    assert [(c["act_code"], c["section"]) for c in fake.search_calls] == [
        ("1", "302"),
        ("2", "103"),
    ]
    assert {m.act_key for m in result.resolution["gujarat"]} == {"ipc", "bns"}


# ------------------------------------------------------------------
# Courts where the act isn't listed, and failures
# ------------------------------------------------------------------


async def test_act_missing_from_a_court_is_reported_not_searched(search):
    """Allahabad lists no BNS: no search is sent, and resolution says why."""
    fake = _use(search, FakeHC({"13": ALLAHABAD_ACTS, "26": DELHI_ACTS}))

    result = await search.cases(act="BNS", courts=["allahabad", "delhi"])

    assert fake.search_calls == []
    assert result.resolution == {"allahabad": [], "delhi": []}
    assert result.hits == []


async def test_one_court_failing_keeps_the_others(search):
    # Delhi's real list carries IPC as code "1"; Gujarat's search for it fails.
    fake = FakeHC(
        {"26": DELHI_ACTS, "17": {"9": "PENAL CODE, 1860"}},
        {"1": [_case("DLHC010000012024")]},
        fail_codes={"9"},
    )
    _use(search, fake)

    result = await search.cases(act="IPC", courts=["delhi", "gujarat"])

    assert [h.case.cnr_number for h in result.hits] == ["DLHC010000012024"]
    assert "gujarat" in result.errors
    assert "CaptchaError" in result.errors["gujarat"]
    assert "delhi" not in result.errors


async def test_act_list_failure_is_recorded(search):
    _use(search, FakeHC({"26": ConnectionError("portal down")}))

    result = await search.cases(act="IPC", courts="delhi")

    assert result.errors["delhi"].startswith("act list: ConnectionError")
    assert "delhi" not in result.resolution


# ------------------------------------------------------------------
# Validation, courts, benches, cache
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"section": "138/141"}, "letters, digits and spaces"),
        ({"status": "All"}, "status"),
        ({"courts": "nowhere"}, "unknown court"),
        ({"courts": "sci"}, "not a High Court"),
    ],
)
async def test_invalid_input_raises_before_any_request(search, kwargs, match):
    fake = _use(search, FakeHC({"26": DELHI_ACTS}))
    args = {"act": "NI Act", "courts": "delhi", **kwargs}
    with pytest.raises(ValueError, match=match):
        await search.cases(**args)
    assert fake.list_calls == [] and fake.search_calls == []


async def test_all_hc_covers_each_principal_bench_once(search):
    principals = [c for c in list_high_courts() if c.bench is None]
    fake = _use(search, FakeHC({c.state_code: {} for c in principals}))

    result = await search.cases(act="NI Act", courts="all-hc")

    assert len(fake.list_calls) == len(principals) == len({c.state_code for c in principals})
    assert set(result.resolution) == {c.code for c in principals}


async def test_all_benches_fetches_each_benchs_list(search):
    fake = _use(search, FakeHC({"1": {"18": "Negotiable Instruments Act"}}))
    fake.benches = {"1": "Principal", "2": "Nagpur", "3": "Aurangabad"}

    await search.cases(act="NI Act", courts="bombay", all_benches=True)

    assert fake.list_calls == [("1", "1"), ("1", "2"), ("1", "3")]
    assert [c["bench"] for c in fake.search_calls] == ["1", "2", "3"]


async def test_act_lists_come_from_the_cache_second_time(search):
    fake = _use(search, FakeHC({"26": DELHI_ACTS}))

    await search.cases(act="NI Act", courts="delhi")
    await search.cases(act="IPC", courts="delhi")

    assert fake.list_calls == [("26", "1")]


# ------------------------------------------------------------------
# Archive join and judgment search
# ------------------------------------------------------------------


async def test_with_judgments_joins_once_per_court_year(search):
    rows = {
        "18": [
            _case("DLHC010000012024", "Disposed", date(2025, 3, 1)),
            _case("DLHC010000022024", "Disposed", date(2025, 7, 1)),
            _case("DLHC010000042024", "Disposed", date(2024, 11, 1)),
            _case("DLND020026092025", "Disposed", date(2025, 4, 1)),  # trial court CNR
            _case("DLHC010000032024", "Pending"),
        ]
    }
    _use(search, FakeHC({"26": DELHI_ACTS}, rows))
    archived = {
        "DLHC010000012024": [
            Judgment(cnr="DLHC010000012024", title="latest"),
            Judgment(cnr="DLHC010000012024", title="older"),
        ],
        "DLHC010000042024": [Judgment(cnr="DLHC010000042024", title="2024 one")],
    }

    async def fake_search(*, cnr, court, year, limit):
        return [j for c in cnr for j in archived.get(c, [])]

    archive = AsyncMock()
    archive.search = AsyncMock(side_effect=fake_search)

    async def get_archive():
        return archive

    search._get_archive = get_archive  # type: ignore[method-assign]

    result = await search.cases(act="NI Act", courts="delhi", status="Both", with_judgments=True)

    calls = sorted(
        (c.kwargs["year"], c.kwargs["cnr"], c.kwargs["court"].code)
        for c in archive.search.await_args_list
    )
    assert calls == [
        (2024, ["DLHC010000042024"], "delhi"),
        (2025, ["DLHC010000012024", "DLHC010000022024"], "delhi"),
    ]
    titles = {h.case.cnr_number: h.judgment and h.judgment.title for h in result.hits}
    assert titles == {
        "DLHC010000012024": "latest",
        "DLHC010000022024": None,  # disposed, but not in the archive
        "DLHC010000042024": "2024 one",
        "DLND020026092025": None,
        "DLHC010000032024": None,
    }


async def test_with_judgments_survives_an_archive_failure(search):
    _use(
        search,
        FakeHC(
            {"26": DELHI_ACTS}, {"18": [_case("DLHC010000012024", "Disposed", date(2025, 1, 2))]}
        ),
    )
    archive = AsyncMock()
    archive.search = AsyncMock(side_effect=OSError("S3 unreachable"))

    async def get_archive():
        return archive

    search._get_archive = get_archive  # type: ignore[method-assign]

    result = await search.cases(
        act="NI Act", courts="delhi", with_judgments=True, status="Disposed"
    )

    assert [h.judgment for h in result.hits] == [None]
    assert result.errors == {}


async def test_judgments_uses_the_portal_act_filter(search):
    live = AsyncMock()
    live.search = AsyncMock(return_value=SearchResult(items=[]))

    async def get_live():
        return live

    search._get_live = get_live  # type: ignore[method-assign]

    assert await search.judgments(act="Negotiable Instruments Act", section="138") == []
    assert live.search.await_args.args == ("",)
    assert live.search.await_args.kwargs["act"] == "Negotiable Instruments Act"
    assert live.search.await_args.kwargs["section"] == "138"


async def test_result_serialises(search):
    _use(search, FakeHC({"26": DELHI_ACTS}, {"18": [_case("DLHC010000012024")]}))

    data = (await search.cases(act="NI Act", courts="delhi")).to_dict()

    assert data["hits"][0]["court"]["code"] == "delhi"
    assert data["hits"][0]["case"]["cnr_number"] == "DLHC010000012024"
    assert data["resolution"]["delhi"][0]["code"] == "18"
