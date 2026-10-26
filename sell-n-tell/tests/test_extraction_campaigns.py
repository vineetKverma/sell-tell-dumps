"""AIML-2929 campaign registry: repair, encoding, vertical lookup, short descriptions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.extraction.campaigns import Registry, load_registry, repair, short_description  # noqa: E402

CSV = ('Name,Description,Industry__c\n'
       '"MH - MULTIFAMILY Pools 26","Pool chemicals “and” parts. Seller Guidance: https://x.y/z",'
       '"MH - MULTIFAMILY"\n'
       '"2026 Q2 Compact Appliances HS - HOSPITALITYitality","Compact fridges and microwaves.","HS - HOSPITALITY"\n'
       '"Water Heater On Demand Available","Healthcare version.","HL - HEALTHCARE"\n'
       '"Water Heater On Demand Available","Multifamily version.","MH - MULTIFAMILY"\n'
       '"Do Not Use","x","MH - MULTIFAMILY"\n')


@pytest.fixture
def registry(tmp_path) -> Registry:
    p = tmp_path / "campaign_topics.csv"
    p.write_bytes(CSV.encode("cp1252"))                     # the export is Windows-1252
    return load_registry(p)


def test_damaged_names_are_repaired(registry):
    assert registry.lookup("MF Pools 26") is not None
    assert registry.lookup("2026 Q2 Compact Appliances Hospitality") is not None
    assert repair("Appliance On Demand IN - INDUSTRIALallation") == "Appliance On Demand Installation"
    assert repair("IS - PUBLIC SECTORernment") == "government"


def test_a_title_listed_twice_resolves_to_the_visits_vertical(registry):
    assert registry.lookup("Water Heater On Demand Available", "MH").description == "Multifamily version."
    assert registry.lookup("Water Heater On Demand Available", "HL").description == "Healthcare version."
    assert registry.lookup("water heater  on demand AVAILABLE", "TR") is not None   # any row when no match


def test_descriptions_are_short_without_links_and_skip_unknown_titles(registry):
    d = registry.descriptions(["MF Pools 26", "Not A Campaign", "Do Not Use"], "MH")
    assert d == {"MF Pools 26": "Pool chemicals “and” parts."}           # cp1252 quotes decoded
    long = "First sentence here. " * 30
    assert len(short_description(long)) <= 300 and short_description(long).endswith(".")
    assert short_description("x" * 400).endswith("...")


@pytest.mark.skipif(not (Path(_ROOT) / "evals" / "reference" / "campaign_topics.csv").exists(),
                    reason="campaign registry not present")
def test_every_golden_campaign_has_a_description():
    from evals.agent_eval.cases import EVALSET, load_cases
    if not EVALSET.exists():
        pytest.skip("golden eval data not present")
    reg = load_registry(Path(_ROOT) / "evals" / "reference" / "campaign_topics.csv")
    missing = {t for c in load_cases() for t in c.planned_topics if reg.lookup(t, c.vertical) is None}
    assert missing == set()


def test_a_renamed_column_is_an_error_not_an_empty_registry(tmp_path):
    p = tmp_path / "campaign_topics.csv"
    p.write_text('"Campaign Name","Description","Industry__c"\n"MF Pools 26","Pools.","MH - MULTIFAMILY"\n',
                 encoding="utf-8")
    with pytest.raises(ValueError, match="no column Name"):
        load_registry(p)
