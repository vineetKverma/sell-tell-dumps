"""Model-based checking of drafted labels (AIML-2898).

The comparison decides which answers are accepted without a judge, so a too-
generous ``agree`` would wave through exactly the disagreements that matter.
"""

import pytest

from evals.dataset.adjudicate import (
    agree,
    build_judge_prompt,
    normalise_judgement,
    presentation_order,
)
from evals.dataset.answers import NOT_DISCUSSED, NOT_STATED, row_answers
from evals.dataset.draft_labels import load_dispositions
from evals.dataset.fields import load_catalog

LABELS = {1: "Create Opportunity", 8: "Pricing concerns", 99: "Outcome not covered"}
TOPICS = {"HC Q2 Room Air"}


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (NOT_STATED, NOT_STATED, True),
        ("54 rooms", "54 rooms", True),
        ("54 Rooms.", "54 rooms", True),  # case and punctuation
        ("12 units", "12 units a month", True),  # one contains the other
        ("54 rooms", NOT_STATED, False),  # stated vs not stated: the key disagreement
        (NOT_DISCUSSED, "8 - Pricing concerns", False),
        ("8 - Pricing concerns", "1 - Create Opportunity", False),
        ("Meeting", "On-site visit", False),
        ("PM", "property manager", False),  # left for the judge
        ("12", "120 units", False),  # too short to count as contained
    ],
)
def test_agree(a, b, expected):
    assert agree(a, b) is expected


@pytest.mark.parametrize(
    ("key", "answer", "expected"),
    [
        ("event_type", "Meeting", "Meeting"),
        ("event_type", "Visit", None),
        ("event_type", "not stated", NOT_STATED),
        ("event_type", "null", NOT_STATED),
        ("HC Q2 Room Air", "not discussed", NOT_DISCUSSED),
        ("HC Q2 Room Air", "8", "8 - Pricing concerns"),
        ("HC Q2 Room Air", "8 - Pricing concerns", "8 - Pricing concerns"),
        ("HC Q2 Room Air", "42", None),  # not a registry code
        ("U-10", "54 rooms", "54 rooms"),
        ("U-10", "not stated", NOT_STATED),
        ("U-10", "(not stated)", NOT_STATED),
        ("U-10", "", None),
    ],
)
def test_normalise_judgement(key, answer, expected):
    assert normalise_judgement(key, answer, LABELS, TOPICS) == expected


def test_unstated_event_type_becomes_not_stated_in_answers():
    draft = {"event_type": None, "topics": [], "fields": []}
    assert row_answers(draft, LABELS)["event_type"] == NOT_STATED
    assert agree(row_answers(draft, LABELS)["event_type"], NOT_STATED)
    assert not agree(NOT_STATED, "Meeting")  # a guess vs no-clue goes to the judge


def test_presentation_order_is_fixed_per_item_and_not_always_a_first():
    orders = [presentation_order("MH-001", f"U-{n:02d}", "A", "B") for n in range(1, 21)]
    assert orders == [presentation_order("MH-001", f"U-{n:02d}", "A", "B") for n in range(1, 21)]
    assert ("A", "B") in orders and ("B", "A") in orders


def test_judge_prompt_shows_both_answers_and_the_rules():
    record = {
        "id": "HL-002", "vertical": "HL", "note": "Looking to replace lighting. 54 rooms.",
        "objective": "PLAN TEXT",
        "topics": [{"title": "HC Q2 Room Air", "description_short": ""}],
    }
    prompt = build_judge_prompt(
        record, load_catalog(), load_dispositions(),
        [("U-10", "54 rooms", NOT_STATED), ("HC Q2 Room Air", "8 - Pricing concerns", NOT_DISCUSSED)],
    )
    assert "54 rooms" in prompt and NOT_STATED in prompt
    assert "answer 1:" in prompt and "answer 2:" in prompt
    assert "answer A" not in prompt  # the judge is never told which draft is which
    assert "U-10 Denominating count" in prompt
    assert "Never infer or guess" in prompt  # same rules as the drafter
    assert "54 rooms." in prompt  # the dictation itself
    assert "PLAN TEXT" not in prompt  # never the pre-call objective
