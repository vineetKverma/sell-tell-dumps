"""Merging, checking, freezing and exporting the golden set (AIML-2898).

The merge decides which answers the agent is scored on; a record that slips
past the checks would be ground truth nobody can trust.
"""

import copy
import json

import pytest

from evals.dataset.draft_labels import load_dispositions
from evals.dataset.export_adk import expected_args, session_state, to_eval_case
from evals.dataset.fields import load_catalog
from evals.dataset.finalize import check_record, merge_record
from evals.dataset.text import VERTICALS


@pytest.fixture(scope="module")
def field_ids():
    catalog = load_catalog()
    return {v: [f.field_id for f in catalog.fields_for(v)] for v in VERTICALS}


@pytest.fixture(scope="module")
def codes():
    return {int(d["code"]) for d in load_dispositions()}


@pytest.fixture
def rec(field_ids):
    fields = dict.fromkeys(field_ids["HL"])
    fields.update({"U-10": "54 rooms", "HL-05": "1.5 ft LED light", "U-03": "HC Q2 Room Air: not discussed"})
    return {
        "id": "HL-002", "vertical": "HL", "campaign_type": "standard_sales",
        "note": "Looking to replace lighting around the building. foot and a half LED light. 54 rooms.",
        "topics": [{"title": "HC Q2 Room Air", "description_short": "Room air promo"}],
        "strata": ["count with unit"], "picked_for": "count with unit",
        "expected": {
            "event_type": None,
            "topics": [{"title": "HC Q2 Room Air", "discussed": False, "disposition_code": None}],
            "fields": fields,
        },
        "reviewed_by": "LLM check: A=x",
    }


# --- merge -------------------------------------------------------------------


def test_identical_keys_have_nothing_contested(rec):
    assert merge_record(rec, copy.deepcopy(rec))["expected"]["contested"] == []


def test_wording_difference_is_not_contested(rec):
    other = copy.deepcopy(rec)
    other["expected"]["fields"]["U-10"] = "54 Rooms."
    assert merge_record(rec, other)["expected"]["contested"] == []


def test_disagreements_are_contested_and_values_come_from_a(rec):
    other = copy.deepcopy(rec)
    other["expected"]["fields"]["HL-05"] = None  # stated in A only
    other["expected"]["event_type"] = "On-site visit"  # no clue vs a guess
    merged = merge_record(rec, other)
    assert merged["expected"]["contested"] == ["HL-05", "event_type"]
    assert merged["expected"]["fields"]["HL-05"] == "1.5 ft LED light"
    assert "reviewed_by" not in merged
    assert merged["built_by"] == ["LLM check: A=x", "LLM check: A=x"]  # both keys recorded


def test_merge_repairs_registry_damage_left_in_a_description(rec):
    rec["topics"][0]["description"] = "Target roles responsible for IS - PUBLIC SECTORernment sites."
    merged = merge_record(rec, copy.deepcopy(rec))
    assert merged["topics"][0]["description"] == "Target roles responsible for government sites."


def test_merge_cleans_descriptions_and_drops_build_leftovers(rec):
    rec["topics"][0]["description"] = "Promo line one.\r\n- bullet\r\n"
    rec["drafted_at"] = "2026-09-25T12:00:00+00:00"
    merged = merge_record(rec, copy.deepcopy(rec))
    assert "\r" not in merged["topics"][0]["description"]
    assert merged["topics"][0]["description"] == "Promo line one.\n- bullet"
    assert "drafted_at" not in merged


def test_derived_field_is_never_contested(rec):
    other = copy.deepcopy(rec)
    other["expected"]["fields"]["U-03"] = "worded differently"
    assert merge_record(rec, other)["expected"]["contested"] == []


# --- checks ------------------------------------------------------------------


def test_a_good_record_passes(rec, field_ids, codes):
    assert check_record(merge_record(rec, rec), field_ids, codes) == []


def test_unmasked_personal_data_is_a_problem(rec, field_ids, codes):
    rec["note"] += " Call 555-123-4567."
    assert any("email, phone or long number" in p for p in check_record(rec, field_ids, codes))


def test_missing_field_is_a_problem(rec, field_ids, codes):
    del rec["expected"]["fields"]["HL-09"]
    assert any("field set" in p for p in check_record(rec, field_ids, codes))


def test_invalid_disposition_is_a_problem(rec, field_ids, codes):
    rec["expected"]["topics"][0].update(discussed=True, disposition_code=42)
    assert any("has code 42" in p for p in check_record(rec, field_ids, codes))


def test_topics_must_match_the_plan(rec, field_ids, codes):
    rec["expected"]["topics"][0]["title"] = "Something else"
    assert any("do not match the planned topics" in p for p in check_record(rec, field_ids, codes))


# --- ADK export ----------------------------------------------------------------


def test_eval_case_is_valid_adk_and_carries_the_golden_answers(rec):
    pytest.importorskip("google.adk")
    from google.adk.evaluation.eval_set import EvalSet  # noqa: PLC0415

    merged = merge_record(rec, rec)
    case = to_eval_case(merged)
    # Round-trip through ADK's own schema: this is what `adk eval` will load.
    loaded = EvalSet.model_validate_json(
        EvalSet(eval_set_id="t", eval_cases=[case]).model_dump_json()
    )
    call = loaded.eval_cases[0].conversation[0].intermediate_data.tool_uses[0]
    assert call.name == "stage_visit_notes"
    assert call.args == json.loads(json.dumps(expected_args(merged)))
    assert call.args["must_capture"]["U-10"] == "54 rooms"
    assert loaded.eval_cases[0].conversation[0].user_content.parts[0].text == rec["note"]
    assert loaded.eval_cases[0].session_input.state == session_state(merged)
    assert session_state(merged)["planned_topics"] == ["HC Q2 Room Air"]


def test_eval_case_uses_only_declared_adk_fields(rec):
    """Some ADK versions forbid extra fields on an EvalCase (extra="forbid");
    the installed one may allow them, so check against the declared fields."""
    pytest.importorskip("google.adk")
    from google.adk.evaluation.eval_case import (  # noqa: PLC0415
        EvalCase,
        Invocation,
        SessionInput,
    )

    case = to_eval_case(merge_record(rec, rec))
    assert set(case.model_dump(exclude_none=True)) <= set(EvalCase.model_fields)
    assert set(case.session_input.model_dump(exclude_none=True)) <= set(SessionInput.model_fields)
    for inv in case.conversation:
        assert set(inv.model_dump(exclude_none=True)) <= set(Invocation.model_fields)
