"""Tests for act-name resolution, the act-list cache and the crosswalk.

Resolution tests run against real High Court act lists captured live
(``tests/fixtures/acts/``): Delhi and Karnataka whole, and excerpts of
Gujarat, Allahabad and Bombay holding every entry whose name touches the
acts tested here — so an absence in an excerpt is an absence in the list.
"""

import os
import time
from pathlib import Path

import pytest

from bharat_courts import acts
from bharat_courts.acts import (
    ACTS,
    Act,
    _ActListCache,
    lookup_acts,
    normalize_act_name,
    resolve,
    successor_sections,
)
from bharat_courts.hcservices.parser import parse_code_name_list

ACT_LISTS = Path(__file__).parent / "fixtures" / "acts"


def _court(name: str) -> dict[str, str]:
    return parse_code_name_list((ACT_LISTS / f"{name}.txt").read_text(encoding="utf-8"))


def _codes(query, act_list) -> set[str]:
    return {m.code for m in resolve(query, act_list)}


# ------------------------------------------------------------------
# Normalisation
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("The Negotiable Instruments Act, 1881", "negotiable instrument"),
        ("NEGOTIABLE INSTRUMENTS ACT", "negotiable instrument"),
        ("Indian Penal Code (I.P.C)", "indian penal code"),
        ("I.P.C(POLICE)", "ipc"),
        ("INDIAN PENAL CODE1", "indian penal code"),
        ("ARBITRATION &amp; CONCILIATION ACT, 1996", "arbitration and conciliation"),
        (
            "NARCOTIC DRUGS AND PSYCHOTROPIC SUBSTANCES ACT, 1985 (61 OF 1985)",
            "narcotic drug and psychotropic substance",
        ),
        (
            "Code of Criminal Procedure (Bombay Amendment) Act",
            "code of criminal procedure bombay amendment",
        ),
        ("Income-tax Act, 1961", "income tax"),
        ("239 CR.P.C", "crpc"),
    ],
)
def test_normalize_act_name(raw, expected):
    assert normalize_act_name(raw) == expected


def test_normalize_keeps_years_aside():
    assert acts._normalize("Code of Criminal Procedure, 1973, 1974").years == {1973, 1974}
    assert acts._normalize("ARBITRATION ACT1940").years == {1940}
    assert acts._normalize("NDPS ACT, 1985 (61 OF 1985)").years == {1985}


# ------------------------------------------------------------------
# Curated table lookup
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "keys"),
    [
        ("IPC", ["ipc"]),
        ("Indian Penal Code, 1860", ["ipc"]),
        ("ni act", ["ni"]),
        ("CrPC", ["crpc"]),
        ("CPC", ["cpc"]),
        ("Companies Act", ["companies-2013", "companies-1956"]),
        ("Companies Act, 2013", ["companies-2013"]),
        ("Domestic Violance", ["dv"]),  # misspelt query still names the act
        ("Motor Vehicles Act 1939", []),  # only the 1988 Act is curated
        ("Gram Nyayalayas Act", []),
        ("", []),
    ],
)
def test_lookup_acts(query, keys):
    assert [a.key for a in lookup_acts(query)] == keys


def test_curated_keys_line_up_with_crosswalk():
    for old, new in (("ipc", "bns"), ("crpc", "bnss"), ("iea", "bsa")):
        assert ACTS[old].successor == new
        assert new in ACTS


# ------------------------------------------------------------------
# Resolution against real court lists
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("court", "name"),
    [
        ("delhi_hc", "INDIAN PENAL CODE"),
        ("gujarat_hc_excerpt", "PENAL CODE, 1860"),
        ("karnataka_hc", "INDIAN PENAL CODE1"),
        ("bombay_hc_excerpt", "Indian Penal Code (I.P.C)"),
    ],
)
def test_ipc_resolves_whatever_the_court_calls_it(court, name):
    matches = resolve("IPC", _court(court))
    assert [m.name for m in matches] == [name]
    assert matches[0].tier == "alias"
    assert matches[0].act_key == "ipc"


def test_allahabad_has_both_ipc_spellings():
    names = {m.name for m in resolve("IPC", _court("allahabad_hc_excerpt"))}
    assert names == {"INDIAN PENAL CODE", "I.P.C(POLICE)"}


def test_act_missing_from_a_court_resolves_to_nothing():
    """Allahabad lists no BNS entry at all — the caller must be told, not guessed for."""
    assert resolve("BNS", _court("allahabad_hc_excerpt")) == []
    assert resolve("BNS", _court("gujarat_hc_excerpt"))


def test_one_act_returns_every_code_it_is_filed_under():
    """Delhi files 1996-Act arbitrations under three codes; the 1940 Act stays out."""
    delhi = _court("delhi_hc")
    assert _codes("arbitration", delhi) == {"227", "165", "202"}
    assert {"225", "170"} <= _codes("Arbitration Act 1940", delhi)


def test_civil_and_criminal_procedure_never_cross():
    delhi = _court("delhi_hc")
    crpc, cpc = _codes("CrPC", delhi), _codes("CPC", delhi)
    assert crpc and cpc
    assert not crpc & cpc


def test_year_tells_versions_apart():
    acts_list = {
        "1": "Motor Vehicles Act, 1939",
        "2": "MOTOR VEHICLES ACT-1988",
        "3": "Motor Vehicles Act",
    }
    assert _codes("MV Act", acts_list) == {"2", "3"}


def test_amendment_acts_do_not_match_the_parent():
    bombay = _court("bombay_hc_excerpt")
    names = {m.name for m in resolve("CrPC", bombay)}
    assert names
    assert not any("Amendment" in n for n in names)


def test_near_miss_spellings_match():
    gujarat = _court("gujarat_hc_excerpt")
    matches = {m.name: m.tier for m in resolve("DV Act", gujarat)}
    assert matches == {
        "Protection of woman from domestic violence Act 2005": "fuzzy",
        "Domestic Violance Act 2005": "fuzzy",
    }


@pytest.mark.parametrize(
    "instrument",
    [
        "Narcotic Drugs And Psychotropic Substances Rules",
        "Protection of Children from Sexual Offences Rules",
        "NARCOTIC DRUGS AND PSYCHOTROPIC SUBSTANCES (REGULATION OF CONTROLLED SUBSTANCE) "
        "ORDER, 1993",
    ],
)
def test_rules_and_orders_never_answer_for_the_act(instrument):
    """These score above the fuzzy threshold, so only the qualifier guard stops them."""
    assert resolve("NDPS", {"9": instrument}) == []
    assert resolve("POCSO", {"9": instrument}) == []


def test_free_text_tiers():
    acts_list = {
        "1": "Gram Nyayalayas Act",
        "2": "Gram Nyayalayas (Amendment) Act",
        "3": "Bombay Shops and Establishments Act",
    }
    exact = resolve("Gram Nyayalayas Act", acts_list)
    assert [(m.code, m.tier) for m in exact] == [("1", "exact")]
    token = resolve("shops establishments", acts_list)
    assert [(m.code, m.tier) for m in token] == [("3", "token")]
    assert resolve("Something Entirely Else", acts_list) == []


def test_resolve_accepts_an_act():
    assert _codes(ACTS["ni"], _court("delhi_hc")) == {"18"}


def test_matches_serialise():
    m = resolve("IPC", _court("delhi_hc"))[0]
    assert m.to_dict() == {
        "code": "1",
        "name": "INDIAN PENAL CODE",
        "tier": "alias",
        "score": 1.0,
        "act_key": "ipc",
    }


# ------------------------------------------------------------------
# Act-list cache
# ------------------------------------------------------------------


def test_cache_round_trip(tmp_path):
    cache = _ActListCache(cache_dir=tmp_path)
    key = cache.hc_key("26", "1")
    assert cache.load(key) is None
    cache.save(key, {"18": "NEGOTIABLE INSTRUMENTS ACT, 1881"})
    assert cache.load(key) == {"18": "NEGOTIABLE INSTRUMENTS ACT, 1881"}
    assert not list(tmp_path.glob(".w_*"))  # temp file renamed into place


def test_cache_ttl_zero_is_always_stale(tmp_path):
    """``ttl_seconds or DEFAULT`` would turn 0 into a week (CLAUDE.md gotcha #5)."""
    cache = _ActListCache(cache_dir=tmp_path, ttl_seconds=0)
    cache.save("hc_26_1", {"1": "INDIAN PENAL CODE"})
    assert cache.ttl_seconds == 0
    assert cache.load("hc_26_1") is None


def test_cache_expires(tmp_path):
    cache = _ActListCache(cache_dir=tmp_path, ttl_seconds=60)
    cache.save("hc_26_1", {"1": "INDIAN PENAL CODE"})
    old = time.time() - 120
    os.utime(tmp_path / "hc_26_1.json", (old, old))
    assert cache.load("hc_26_1") is None


def test_cache_ttl_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("BHARAT_COURTS_ACTS_TTL_DAYS", "0.5")
    assert _ActListCache(cache_dir=tmp_path).ttl_seconds == 43200


def test_cache_skips_empty_lists_and_corrupt_files(tmp_path):
    cache = _ActListCache(cache_dir=tmp_path)
    cache.save("hc_26_1", {})
    assert not (tmp_path / "hc_26_1.json").exists()
    (tmp_path / "hc_26_2.json").write_text("{not json")
    assert cache.load("hc_26_2") is None


def test_cache_keys():
    assert _ActListCache.hc_key("1", "2") == "hc_1_2"
    assert _ActListCache.dc_key("26", "1", "1260001", "") == "dc_26_1_1260001_0"
    with pytest.raises(ValueError):
        _ActListCache(cache_dir="/tmp/x").load("../escape")


# ------------------------------------------------------------------
# Crosswalk
# ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("act", "section", "expected"),
    [
        ("ipc", "302", [("103(1)", "103")]),
        ("ipc", "420", [("318(4)", "318")]),
        ("ipc", "498a", [("85", "85"), ("86", "86")]),
        ("ipc", "376(2)", [("64", "64"), ("65(1)", "65")]),
        ("ipc", "171I", [("177", "177")]),  # printed "171-I" in the source
        ("ipc", "231", [("178", "178")]),  # inside "230 to 232" in the source
        ("crpc", "438", [("482", "482")]),
        ("crpc", "482", [("528", "528")]),
        ("iea", "65B", [("63", "63")]),
        ("iea", "27", [("Proviso to section 23", "23")]),
    ],
)
def test_successor_sections(act, section, expected):
    got = [(m.new_section, m.new_section_base) for m in successor_sections(act, section)]
    assert got == expected


def test_successor_sections_accepts_names_and_acts():
    assert successor_sections("Indian Penal Code", "302")[0].new_act == "bns"
    assert successor_sections(ACTS["crpc"], "439")[0].new_section == "483"


def test_successor_sections_cite_their_source():
    m = successor_sections("ipc", "302")[0]
    assert m.source.endswith("comparison_summary_BNS_to_IPC.pdf")
    assert m.source_page > 0


@pytest.mark.parametrize(("act", "section"), [("ni", "138"), ("ipc", "99999"), ("bns", "103")])
def test_no_successor(act, section):
    assert successor_sections(act, section) == []


def test_crosswalk_ships_as_package_data():
    from importlib import resources

    assert (resources.files("bharat_courts") / "data" / "crosswalk.csv").is_file()


def test_act_is_serialisable():
    assert Act("x", "X Act", 2000).to_dict()["year"] == 2000
