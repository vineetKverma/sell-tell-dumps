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


@pytest.mark.parametrize("fid,text,ok", [
    ("HS-08", "dropped off filters", False),                       # topic only
    ("HS-08", "they have 140 PTACs, filters changed quarterly", True),
    ("HL-05", "measured the window, 36\" x 48\"", True),
    ("HL-05", "ordered 36 gloves", False),
    ("MH-04", "Home Depot is cheaper", False),                    # no amount
    ("MH-04", "Home Depot quoted $42 for the same unit", True),
    ("HL-09", "no need, they already order through Amazon", True),
    ("HL-09", "no need at this time", False),
    ("TR-06", "talked about the job", False),
    ("TR-06", "next job is the Elm St remodel, needs rough-in valves", True),
    ("HS-09", "chief engineer is low on ballasts in the shop", True),
])
def test_strict_patterns_want_the_detail_not_the_topic(fid, text, ok):
    from evals.dataset.sample_topup import matches
    assert matches(fid, text, strict=True) is ok


def test_strict_falls_back_to_broad_for_fields_without_a_strict_pattern():
    from evals.dataset.sample_topup import matches
    assert matches("HL-01", "orders through DSSI", strict=True)


def test_synthetic_records_are_marked_and_target_only_the_absent_fields():
    from evals.dataset.make_synthetic import CASES, records

    class Hit:
        description, industry = "A campaign.", "HS - HOSPITALITY"

    class Index:
        def lookup(self, title, vertical):
            return Hit()

    recs = records(Index())
    assert len(recs) == len(CASES) == 6
    assert {r["picked_for"] for r in recs} == {"field:HS-08", "field:HS-09"}
    assert all(r["synthetic"] and r["id"].startswith("S-") and r["source_row"] < 0 for r in recs)
    assert all(r["industry"] == "HS - HOSPITALITY" and r["topics"] for r in recs)


def test_synthetic_refuses_a_topic_missing_from_the_registry():
    from evals.dataset.make_synthetic import records

    class Index:
        def lookup(self, title, vertical):
            return None

    with pytest.raises(SystemExit):
        records(Index())


def test_second_round_draws_only_the_named_fields():
    picked = draw_targets(_pool(), per_field=5, seed=1, exclude_rows=set(), fields=["MH-06"])
    assert picked == [(14, "field:MH-06")]


def test_second_round_skips_notes_from_earlier_samples(tmp_path):
    import json

    from evals.dataset.sample_topup import golden_source_rows
    (tmp_path / "golden_v1.jsonl").write_text(json.dumps({"source_row": 1}) + "\n", encoding="utf-8")
    (tmp_path / "sample_topup_a.jsonl").write_text(
        "".join(json.dumps({"source_row": r}) + "\n" for r in (10, 11)), encoding="utf-8")
    assert golden_source_rows(tmp_path) == {1}
    assert golden_source_rows(tmp_path, ["topup_a"]) == {1, 10, 11}
    with pytest.raises(SystemExit):
        golden_source_rows(tmp_path, ["no_such_run"])


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
