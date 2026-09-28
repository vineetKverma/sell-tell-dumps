"""Golden dataset curation helpers (AIML-2898).

Covers the decisions that would silently corrupt the dataset if they broke:
repairing the damaged Campaign Topics sheet, splitting pre-call topics,
masking, and the checks that stop a drafted label from being trusted when
its quote is not in the note.
"""

import pytest

from evals.dataset import draft_labels
from evals.dataset.answers import derive_topic_status
from evals.dataset.draft_labels import (
    DERIVED_FIELDS,
    EVENT_TYPES,
    build_prompt,
    check_draft,
    is_quote_of,
    labelled_fields,
    load_dispositions,
)
from evals.dataset.fields import load_catalog
from evals.dataset.text import (
    RegistryTopic,
    TopicIndex,
    clean_note,
    damage_count,
    make_splitter,
    mask_pii,
    repair_registry_text,
    short_description,
    strata_for,
)

# --- registry repair --------------------------------------------------------


@pytest.mark.parametrize(
    ("damaged", "repaired"),
    [
        ("2026 Q3 HS - HOSPITALITYitality Managed", "2026 Q3 Hospitality Managed"),
        ("Appliance On Demand IN - INDUSTRIALallation", "Appliance On Demand Installation"),
        ("2026 Q2 MH - MULTIFAMILY Season Refrigerators", "2026 Q2 MF Season Refrigerators"),
        ("roles responsible for IS - PUBLIC SECTORernment facilities", "roles responsible for government facilities"),
        ("HC BM&S Q3 - $15 off $100", "HC BM&S Q3 - $15 off $100"),
    ],
)
def test_registry_damage_is_undone(damaged, repaired):
    assert repair_registry_text(damaged) == repaired


def test_lowercase_damage_still_matches_after_repair():
    # "Comfort" -> "CoMH - MULTIFAMILYort" -> "CoMFort": case differs, so
    # every comparison downstream is case-insensitive.
    index = TopicIndex([RegistryTopic(repair_registry_text("Preferred CoMH - MULTIFAMILYort"), "d", "")])
    assert index.lookup("Preferred Comfort", None) is not None


def test_damage_count_is_zero_after_repair():
    texts = ["2026 Q2 MH - MULTIFAMILY Pools", "IN - INDUSTRIALallation"]
    assert sum(damage_count(texts).values()) == len(texts)
    assert sum(damage_count([repair_registry_text(t) for t in texts]).values()) == 0


# --- topic splitting and lookup --------------------------------------------


def test_split_keeps_titles_that_contain_commas():
    split = make_splitter(["Q2 26 Full Suite Appliances- TX, FL, GA, AZ and NV", "MF Pools 26"])
    cell = "MF Pools 26,Q2 26 Full Suite Appliances- TX, FL, GA, AZ and NV,MF HVAC Q1 26"
    assert sorted(split(cell)) == sorted([
        "Q2 26 Full Suite Appliances- TX, FL, GA, AZ and NV", "MF Pools 26", "MF HVAC Q1 26",
    ])


def test_split_empty_cell():
    assert make_splitter([])(None) == []


def test_lookup_prefers_the_visits_own_vertical():
    index = TopicIndex([
        RegistryTopic("Water Heater On Demand Available", "healthcare copy", "HL - HEALTHCARE"),
        RegistryTopic("Water Heater On Demand Available", "public sector copy", "IS - PUBLIC SECTOR;HL - HEALTHCARE"),
    ])
    assert index.lookup("water heater on demand available", "IS").description == "public sector copy"
    assert index.lookup("Water Heater On Demand Available", "TR").description == "healthcare copy"


def test_do_not_use_is_never_matched():
    index = TopicIndex([RegistryTopic("Do Not Use", "x", "MKTG")])
    assert index.lookup("Do Not Use", None) is None


# --- note cleaning -----------------------------------------------------------


def test_clean_note_fixes_carriage_returns_and_mojibake():
    mojibake = "didn" + chr(0xE2) + chr(0x20AC) + chr(0x2122) + "t"  # didn't, read as cp1252
    assert clean_note(f"line one\r\n{mojibake}_x000D_") == "line one\ndidn" + chr(0x2019) + "t"


def test_mask_pii():
    masked = mask_pii("PO 12345678, mail bob@x.com or 555-123-4567")
    assert masked == "PO [NUMBER], mail [EMAIL] or [PHONE]"


def test_short_description_drops_links_and_cuts_at_a_sentence():
    text = "Seller Guide: https://example.com/abc Discounted pricing. " + "More detail here. " * 40
    limit = 120
    short = short_description(text, limit=limit)
    assert "http" not in short and "Seller Guide" not in short
    assert short.endswith(".") and len(short) <= limit


def test_strata():
    assert "no contact" in strata_for("Office was closed, left a flyer")
    assert "short" in strata_for("Not there")
    assert "count with unit" in strata_for("turning 12 units a month")


# --- label rules stay in step with the agent --------------------------------


def test_event_types_match_the_workflow(workflow):
    assert list(EVENT_TYPES) == list(workflow.VALID_EVENT_TYPES)


def test_disposition_codes_match_the_workflow(workflow):
    assert sorted(int(d["code"]) for d in load_dispositions()) == sorted(workflow.VALID_DISPOSITION_CODES)


# --- rate limits ----------------------------------------------------------------


class _FakeModels:
    """Stands in for client.models: fails with the given errors, then answers."""

    def __init__(self, errors):
        self.errors = list(errors)
        self.calls = 0

    def generate_content(self, **_kwargs):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return type("Response", (), {"text": '{"ok": true}'})()


def _fake_client(errors):
    return type("Client", (), {"models": _FakeModels(errors)})()


def test_rate_limit_is_waited_out(monkeypatch):
    waits = []
    monkeypatch.setattr(draft_labels.time, "sleep", waits.append)
    client = _fake_client([Exception("429 RESOURCE_EXHAUSTED"), Exception("429 RESOURCE_EXHAUSTED")])
    assert draft_labels._generate(client, "m", "p") == '{"ok": true}'
    assert waits == list(draft_labels.RATE_LIMIT_WAITS[:2])


def test_other_errors_are_not_waited_out(monkeypatch):
    monkeypatch.setattr(draft_labels.time, "sleep", lambda _s: pytest.fail("should not wait"))
    with pytest.raises(ValueError, match="bad request"):
        draft_labels._generate(_fake_client([ValueError("400 bad request")]), "m", "p")


def test_rate_limit_that_never_clears_is_raised(monkeypatch):
    monkeypatch.setattr(draft_labels.time, "sleep", lambda _s: None)
    errors = [Exception("429")] * (len(draft_labels.RATE_LIMIT_WAITS) + 1)
    with pytest.raises(Exception, match="429"):
        draft_labels._generate(_fake_client(errors), "m", "p")


# --- draft checks -------------------------------------------------------------

NOTE = "Met with Maria. Turning 12 units a month. Built a quote for 10 microwaves."


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture
def record():
    return {
        "id": "MH-001", "vertical": "MH", "note": NOTE, "objective": "PLAN TEXT",
        "topics": [{"title": "HC Q2 Compact Appliances", "description_short": "Microwaves $69"}],
    }


def _set(draft, field_id, value, evidence):
    for f in draft["fields"]:
        if f["field_id"] == field_id:
            f.update(value=value, evidence=evidence)
            return
    raise KeyError(field_id)


def _draft(catalog, **overrides):
    fields = [
        {"field_id": f.field_id, "value": None, "evidence": ""} for f in labelled_fields(catalog, "MH")
    ]
    draft = {
        "event_type": "Meeting", "event_type_evidence": "Met with Maria",
        "topics": [{"title": "HC Q2 Compact Appliances", "discussed": True,
                    "disposition_code": 1, "evidence": "Built a quote for 10 microwaves"}],
        "fields": fields,
    }
    _set(draft, "U-10", "12 units", "Turning 12 units a month")
    draft.update(overrides)
    return draft


def _check(catalog, record, draft):
    ids = [f.field_id for f in labelled_fields(catalog, "MH")]
    codes = {int(d["code"]) for d in load_dispositions()}
    return check_draft(draft, record, ids, codes)


def test_a_grounded_draft_passes(catalog, record):
    assert _check(catalog, record, _draft(catalog)) == ([], [])


def test_a_quote_that_is_not_in_the_note_is_flagged(catalog, record):
    draft = _draft(catalog)
    _set(draft, "U-06", "Price", "too expensive vs Grainger")
    problems, flags = _check(catalog, record, draft)
    assert problems == []
    assert flags == ["U-06: value without a quote found in the note"]


@pytest.mark.parametrize(
    ("evidence", "expected"),
    [
        ("Met with Maria", True),
        ("met   WITH maria", True),  # case and spacing ignored
        ("Met with ... 12 units a month", True),  # shortened, pieces in order
        ("12 units ... Met with Maria", False),  # pieces out of order
        ("Met with ... 40 units", False),  # one piece not in the note
        ("...", False),
        ("", False),
    ],
)
def test_quote_matching(evidence, expected):
    assert is_quote_of(evidence, NOTE) is expected


def test_shortened_genuine_quote_is_not_flagged(catalog, record):
    draft = _draft(catalog)
    _set(draft, "U-10", "12 units", "Turning ... a month")
    assert _check(catalog, record, draft) == ([], [])


def test_event_type_may_be_left_unstated(catalog, record):
    # "missing toilet paper order" says nothing about how the contact happened.
    assert _check(catalog, record, _draft(catalog, event_type=None, event_type_evidence=""))[0] == []


def test_structural_errors_are_problems(catalog, record):
    problems, _ = _check(catalog, record, _draft(catalog, event_type="Visit", topics=[]))
    assert any("event_type" in p for p in problems)
    assert "topics do not match the planned titles" in problems


def test_not_discussed_topic_cannot_carry_a_code(catalog, record):
    draft = _draft(catalog, topics=[{"title": "HC Q2 Compact Appliances", "discussed": False,
                                     "disposition_code": 3, "evidence": ""}])
    problems, _ = _check(catalog, record, draft)
    assert problems == ["topic 'HC Q2 Compact Appliances': not discussed but has code 3"]


def test_prompt_carries_every_labelled_field_and_never_the_objective(catalog, record):
    prompt = build_prompt(record, catalog, load_dispositions())
    assert all(f"- {f.field_id} |" in prompt for f in labelled_fields(catalog, "MH"))
    assert NOTE in prompt
    assert "PLAN TEXT" not in prompt


def test_u03_is_derived_not_labelled(catalog, record):
    assert "U-03" in DERIVED_FIELDS
    assert "U-03" not in {f.field_id for f in labelled_fields(catalog, "MH")}
    assert len(labelled_fields(catalog, "MH")) == len(catalog.fields_for("MH")) - 1
    assert "- U-03 |" not in build_prompt(record, catalog, load_dispositions())


def test_rules_define_what_stated_means(record, catalog):
    prompt = build_prompt(record, catalog, load_dispositions())
    assert "What counts as STATED" in prompt
    assert "explicit" in prompt and "negative is stated" in prompt
    assert "spoke with target" in prompt  # fixed vocabulary for contact outcome


def test_derived_topic_status():
    labels = {1: "Create Opportunity"}
    topics = [
        {"title": "HC Q2 Room Air", "discussed": False, "disposition_code": None},
        {"title": "MF Pools 26", "discussed": True, "disposition_code": 1},
    ]
    assert derive_topic_status(topics, labels) == (
        "HC Q2 Room Air: not discussed | MF Pools 26: discussed - 1 Create Opportunity"
    )
