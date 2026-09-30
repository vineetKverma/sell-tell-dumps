"""Field-targeted top-up: pattern table, draw, and the finalize filter. No model."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

pd = pytest.importorskip("pandas")

from evals.agent_eval.cases import load_cases  # noqa: E402
from evals.dataset.fields import load_catalog  # noqa: E402
from evals.dataset.finalize import keep_target_stated  # noqa: E402
from evals.dataset.sample_topup import PATTERNS, TARGETS, draw_targets, vertical_of  # noqa: E402


def test_targets_are_exactly_the_vertical_fields_golden_v1_never_states():
    stated: dict[str, int] = {}
    for c in load_cases():
        for fid, v in c.fields.items():
            stated[fid] = stated.get(fid, 0) + (v not in (None, ""))
    never = {f for f, n in stated.items() if n == 0 and not f.startswith("U-")}
    assert set(TARGETS) == never
    assert len(TARGETS) == 33


def test_every_target_is_a_field_of_its_own_vertical():
    cat = load_catalog()
    for fid in TARGETS:
        assert fid in {f.field_id for f in cat.fields_for(vertical_of(fid))}


@pytest.mark.parametrize("fid,text", [
    ("HL-01", "They order through DSSI now"),
    ("HL-03", "120 bed skilled nursing facility, census is down"),
    ("HL-05", "the opening is 24\" wide"),
    ("HS-08", "needs PTAC filters for 200 rooms"),
    ("IS-06", "NSPIRE inspection next month"),
    ("MH-02", "HVAC unit will be replaced not repaired"),
    ("MH-06", "two water heaters out"),
    ("TR-02", "Ferguson is 10% cheaper"),
    ("TR-09", "the homeowner wants it by Friday"),
])
def test_pattern_finds_a_plain_mention(fid, text):
    assert PATTERNS[fid].search(text)


@pytest.mark.parametrize("fid,text", [
    ("MH-02", "talked HVAC filters"),       # a mention, not a repair-vs-replace posture
    ("HL-08", "left a catalog"),
    ("IS-06", "shipped the order"),
])
def test_pattern_ignores_unrelated_notes(fid, text):
    assert not PATTERNS[fid].search(text)


def _pool():
    rows = [("HL", "They order through DSSI"), ("HL", "DSSI punchout set up"),
            ("HL", "left a catalog"), ("MH", "DSSI mentioned"),  # wrong vertical
            ("MH", "two water heaters out"), ("HL", "DSSI again")]
    return pd.DataFrame(rows, columns=["vertical", "note_clean"], index=[10, 11, 12, 13, 14, 15])


def test_draw_takes_matching_notes_from_the_fields_own_vertical_only():
    picked = draw_targets(_pool(), per_field=5, seed=1, exclude_rows=set())
    hl01 = sorted(i for i, why in picked if why == "field:HL-01")
    assert hl01 == [10, 11, 15]
    assert (14, "field:MH-06") in picked


def test_draw_skips_golden_rows_caps_per_field_and_uses_each_note_once():
    picked = draw_targets(_pool(), per_field=1, seed=1, exclude_rows={10})
    rows = [i for i, _ in picked]
    assert 10 not in rows
    assert len(rows) == len(set(rows))
    assert sum(why == "field:HL-01" for _, why in picked) == 1


def test_draw_is_repeatable_so_both_builds_label_the_same_notes():
    assert draw_targets(_pool(), 2, 7, set()) == draw_targets(_pool(), 2, 7, set())


def test_labeller_unwraps_a_one_item_list_and_rejects_other_shapes():
    from evals.dataset.draft_labels import as_object
    obj = {"event_type": "Meeting"}
    assert as_object(obj) is obj
    assert as_object([obj]) is obj
    assert as_object([obj, obj]) is None
    assert as_object(["x"]) is None
    assert as_object([]) is None
    assert as_object("text") is None


def _rec(rid, fid, value, contested=()):
    return {"id": rid, "picked_for": f"field:{fid}",
            "expected": {"fields": {fid: value}, "contested": list(contested)}}


def test_finalize_keeps_only_confirmed_targets_up_to_the_cap():
    merged = [
        _rec("T-HL-001", "HL-01", "DSSI"),
        _rec("T-HL-002", "HL-01", None),                      # keyword hit, field not stated
        _rec("T-HL-003", "HL-01", "GPO", contested=["HL-01"]),  # builds disagreed
        _rec("T-HL-004", "HL-01", "punchout"),
        _rec("T-HL-005", "HL-01", "portal"),                  # over the cap
        _rec("T-HL-006", "HL-08", None),                      # nothing confirmed for HL-08
    ]
    kept, counts = keep_target_stated(merged, per_field=2)
    assert [r["id"] for r in kept] == ["T-HL-001", "T-HL-004"]
    assert counts == {"HL-01": 2, "HL-08": 0}
