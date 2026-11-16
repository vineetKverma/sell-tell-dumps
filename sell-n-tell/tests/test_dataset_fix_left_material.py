"""Golden v1.4 -> v1.5: material or a voicemail left with no one spoken to is
not discussed. Only the two listed campaigns change, and only from the values
they were reviewed with; the entries the other answers confirm are checked."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evals.dataset.fix_event_types import stage_args  # noqa: E402
from evals.dataset.fix_left_material import CONFIRMED_TOPICS, TO_NOT_DISCUSSED, apply  # noqa: E402


def _case(cid, topics, event_type="On-site visit", u03=None):
    fields = {"U-02": "no contact"}
    if u03 is not None:
        fields["U-03"] = u03
    return {"eval_id": cid, "conversation": [{"intermediate_data": {"tool_uses": [
        {"name": "stage_visit_notes", "args": {"event_type": event_type, "contested": [], "must_capture": fields,
                                                "topics": [{"topic": t, "discussed": d, "disposition_code": c}
                                                           for t, d, c in topics]}}]}}]}


def _cases():
    pool = TO_NOT_DISCUSSED["HS-013"]
    return [
        _case("HL-007", [(TO_NOT_DISCUSSED["HL-007"], True, 99)],
              u03=f"{TO_NOT_DISCUSSED['HL-007']}: discussed - 99 Outcome not covered - needs manual review"),
        _case("HS-013", [("Housekeeping Essentials", False, None), (pool, True, 99)],
              u03=f"Housekeeping Essentials: not discussed | {pool}: discussed - 99 Outcome not covered - needs manual review"),
        _case("IN-005", [("2026 Q2 Everyday Essentials - IND", False, None)]),
        _case("IS-007", [("[L3J] PS Everyday Essentials - Q2 2026", False, None),
                         ("Full Suites Appliances - Q2 2026 PS", False, None)], "Phone Call"),
        _case("MH-006", [("Q2 26 MF Full Suites Appliances", True, 1), ("Other", True, 99)], "Meeting"),
        _case("HL-010", [("HC Q2 Ecolab Scientific Clean", True, 5)], "Meeting"),
        _case("IS-003", [("Floor Care - PS Q2 2026", False, None)], "Meeting"),
        _case("TR-001", [("Untouched", True, 99)], "Meeting", u03="Untouched: discussed - 99 Outcome not covered"),
    ]


def _set(cases, set_id="sellntell_golden_v1.4"):
    return {"eval_set_id": set_id, "name": "n", "description": "d", "eval_cases": cases}


def test_left_with_nobody_spoken_to_becomes_not_discussed_and_nothing_else_moves():
    before = _set(_cases())
    after = apply(copy.deepcopy(before))
    out = {c["eval_id"]: stage_args(c) for c in after["eval_cases"]}
    assert after["eval_set_id"] == "sellntell_golden_v1.5"
    assert out["HL-007"]["topics"] == [{"topic": TO_NOT_DISCUSSED["HL-007"], "discussed": False, "disposition_code": None}]
    assert out["HL-007"]["must_capture"]["U-03"] == f"{TO_NOT_DISCUSSED['HL-007']}: not discussed"
    pool = TO_NOT_DISCUSSED["HS-013"]
    assert out["HS-013"]["topics"][1] == {"topic": pool, "discussed": False, "disposition_code": None}
    assert out["HS-013"]["topics"][0]["discussed"] is False                      # its other campaign as it was
    assert out["HS-013"]["must_capture"]["U-03"] == f"Housekeeping Essentials: not discussed | {pool}: not discussed"
    was = {c["eval_id"]: stage_args(c) for c in before["eval_cases"]}
    for cid in ("IN-005", "IS-007", "MH-006", "HL-010", "IS-003", "TR-001"):     # confirmed or unlisted: untouched
        assert out[cid] == was[cid], cid


def test_only_v14_and_only_with_the_reviewed_values():
    with pytest.raises(SystemExit, match="v1.4 only"):
        apply(_set(_cases(), "sellntell_golden_v1.5"))                           # a second run is refused
    moved = _cases()
    stage_args(moved[0])["topics"][0]["disposition_code"] = 3                    # HL-007 no longer "discussed, 99"
    with pytest.raises(SystemExit, match="HL-007: 'HC Improve the Room' is discussed=True code=3"):
        apply(_set(moved))
    quote = _cases()
    stage_args(quote[4])["topics"][0]["disposition_code"] = 99                   # MH-006: the quote must be code 1
    with pytest.raises(SystemExit, match="MH-006"):
        apply(_set(quote))
    phone = _cases()
    stage_args(phone[6])["event_type"] = "Phone Call"                            # IS-003 must be a Meeting
    with pytest.raises(SystemExit, match="IS-003: event type is 'Phone Call'"):
        apply(_set(phone))
    with pytest.raises(SystemExit, match="IN-005: not in the set"):
        apply(_set([c for c in _cases() if c["eval_id"] != "IN-005"]))
    gone = _cases()
    stage_args(gone[1])["topics"].pop()                                          # HS-013 lost its campaign
    with pytest.raises(SystemExit, match="HS-013: no campaign"):
        apply(_set(gone))


def test_a_refused_set_is_left_as_it_was():
    data = _set(_cases())
    stage_args(data["eval_cases"][5])["topics"][0]["disposition_code"] = 99      # HL-010 not code 5: refused
    before = copy.deepcopy(data)
    with pytest.raises(SystemExit):
        apply(data)
    assert data == before                                                        # checked first, changed after


def test_every_confirmed_entry_is_one_the_answers_cover():
    assert {cid for cid, *_ in CONFIRMED_TOPICS} == {"IN-005", "IS-007", "MH-006", "HL-010"}
