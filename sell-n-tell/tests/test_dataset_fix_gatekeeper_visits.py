"""Golden v1.3 -> v1.4: front desk only is an On-site visit. Only the listed
cases change, and only from the value they were reviewed with."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evals.dataset.fix_event_types import stage_args  # noqa: E402
from evals.dataset.fix_gatekeeper_visits import apply  # noqa: E402


def _case(cid, event_type="Meeting", contested=()):
    return {"eval_id": cid, "conversation": [{"intermediate_data": {"tool_uses": [
        {"name": "stage_visit_notes", "args": {"event_type": event_type, "contested": list(contested),
                                                "must_capture": {"U-02": "spoke with contact"}}}]}}]}


def _set(cases, set_id="sellntell_golden_v1.3"):
    return {"eval_set_id": set_id, "name": "n", "description": "d", "eval_cases": cases}


def test_front_desk_only_becomes_on_site_and_the_unclear_case_is_contested():
    data = _set([_case("HS-007", contested=["HS-01"]), _case("HL-011"), _case("TR-006"), _case("MH-001")])
    out = {c["eval_id"]: stage_args(c) for c in apply(copy.deepcopy(data))["eval_cases"]}
    assert out["HS-007"]["event_type"] == "On-site visit" and out["HS-007"]["contested"] == ["HS-01", "U-02"]
    assert out["HL-011"]["event_type"] == "Meeting" and out["HL-011"]["contested"] == ["event_type", "U-02"]
    for kept in ("TR-006", "MH-001"):                                     # untouched
        assert out[kept]["event_type"] == "Meeting" and out[kept]["contested"] == []


def test_only_v13_and_only_with_the_reviewed_values():
    cases = [_case("HS-007"), _case("HL-011")]
    with pytest.raises(SystemExit, match="v1.3 only"):
        apply(_set(copy.deepcopy(cases), "sellntell_golden_v1.4"))      # a second run is refused
    with pytest.raises(SystemExit, match="HS-007: event type is 'Phone Call'"):
        apply(_set([_case("HS-007", "Phone Call"), _case("HL-011")]))
    with pytest.raises(SystemExit, match="HL-011: not in the set"):
        apply(_set([_case("HS-007")]))
    out = apply(_set(copy.deepcopy(cases)))
    assert out["eval_set_id"] == "sellntell_golden_v1.4"
