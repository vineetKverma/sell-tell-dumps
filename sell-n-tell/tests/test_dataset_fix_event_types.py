"""Golden v1.1 -> v1.2 event-type fix: only the listed cases change, and only
from a blank, uncontested v1.1 answer."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evals.dataset.fix_event_types import NAMED_PERSON, TO_MEETING, apply, stage_args  # noqa: E402


def _case(cid, event_type=None, contested=()):
    return {"eval_id": cid, "conversation": [{"intermediate_data": {"tool_uses": [
        {"name": "stage_visit_notes", "args": {"event_type": event_type, "contested": list(contested)}}]}}]}


def _set(cases):
    return {"eval_set_id": "sellntell_golden_v1.1", "name": "n", "description": "d", "eval_cases": cases}


def test_only_the_listed_blank_cases_become_meeting():
    data = _set([_case(c) for c in TO_MEETING] + [_case("HS-006"), _case("XX-001", "On-site visit")])
    out = apply(copy.deepcopy(data))
    got = {c["eval_id"]: stage_args(c)["event_type"] for c in out["eval_cases"]}
    assert all(got[c] == "Meeting" for c in TO_MEETING)
    assert got["HS-006"] is None and got["XX-001"] == "On-site visit"      # untouched
    assert out["eval_set_id"] == "sellntell_golden_v1.2"


def test_named_only_leaves_the_unnamed_interactions_blank():
    data = _set([_case(c) for c in TO_MEETING])
    out = apply(data, NAMED_PERSON)
    assert sum(stage_args(c)["event_type"] == "Meeting" for c in out["eval_cases"]) == len(NAMED_PERSON)


@pytest.mark.parametrize("bad,why", [
    (lambda cs: cs.__setitem__(0, _case(TO_MEETING[0], "On-site visit")), "not blank"),
    (lambda cs: cs.__setitem__(0, _case(TO_MEETING[0], None, ["event_type"])), "contested"),
    (lambda cs: cs.pop(0), "not in the set"),
])
def test_it_refuses_a_set_it_was_not_reviewed_against(bad, why):
    cases = [_case(c) for c in TO_MEETING]
    bad(cases)
    with pytest.raises(SystemExit, match=why):
        apply(_set(cases))
    with pytest.raises(SystemExit, match="v1.1 only"):
        apply(dict(_set([_case(c) for c in TO_MEETING]), eval_set_id="sellntell_golden_v1.2"))
