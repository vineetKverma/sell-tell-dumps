"""AIML-2702 scoring, against hand-built agent calls. No model, no network."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# tests/ has no __init__.py, so pytest puts tests/ (not the repo root) on the
# path; add the root so the `evals` package imports without any config change.
_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evals.agent_eval.cases import EVALSET, Case, load_cases, load_priorities  # noqa: E402

# Tests that read the golden set skip when it is not present (it holds customer
# data and may live outside the repo -- see evals/README.md).
needs_data = pytest.mark.skipif(not EVALSET.exists(), reason="golden eval data not present")
from evals.agent_eval.drive import missing_topics  # noqa: E402
from evals.agent_eval.run import scorecard  # noqa: E402
from evals.agent_eval.score import (  # noqa: E402
    DISCUSSED, DUPLICATE, NOT_DISCUSSED, NOT_STAGED,
    aggregate, score_case, value_agrees, variance,
)

PRIO = {"U-01": 1, "U-02": 1, "U-04": 2, "MH-01": 3}


def make_case(**kw) -> Case:
    base = dict(
        id="MH-001", vertical="MH", note="Met Bill. Quoted $3000 on ranges.",
        planned_topics=["Ranges", "Q3 Paint, Primer"],
        event_type="Meeting",
        topics=[{"topic": "Ranges", "discussed": True, "disposition_code": 1},
                {"topic": "Q3 Paint, Primer", "discussed": False, "disposition_code": None}],
        fields={"U-01": "Bill | | unknown", "U-02": None, "U-04": "quote created: $3000",
                "MH-01": None, "U-03": "Ranges: 1"},
        contested=frozenset(),
    )
    base.update(kw)
    return Case(**base)


def perfect(case: Case, with_fields: bool = True) -> dict:
    args = {"event_type": case.event_type or "On-site visit", "executive_summary": "s",
            "topics": [{"topic": t["topic"], "discussed": t["discussed"],
                        "disposition_code": t["disposition_code"]} for t in case.topics]}
    if with_fields:
        args["must_capture"] = dict(case.fields)
    return args


# --- the real golden set -----------------------------------------------------

@needs_data
def test_golden_set_loads_all_90_cases():
    cases = load_cases()
    assert len(cases) == 90
    assert {c.vertical for c in cases} == {"MH", "HS", "HL", "IS", "TR", "IN"}
    assert all(c.note and c.planned_topics for c in cases)
    assert all(len(c.fields) == 20 for c in cases)


@needs_data
def test_priorities_cover_all_65_fields():
    prio = load_priorities()
    assert len(prio) == 65
    assert set(prio.values()) <= {1, 2, 3}
    used = {f for c in load_cases() for f in c.fields}
    assert used <= set(prio)


@needs_data
def test_a_perfect_agent_scores_100_on_the_golden_set():
    cases = load_cases()
    roll = aggregate([score_case(c, perfect(c)) for c in cases], load_priorities())["all"]
    for m in ("event_type", "topic_status", "disposition"):
        assert roll[m]["rate"] == 1.0, m
    assert roll["duplicate_rows"] == roll["off_plan_rows"] == roll["not_staged"] == 0
    f = roll["fields"]["all"]
    assert f["recall"] == 1.0 and f["fabrication"] == 0.0 and f["value_accuracy"] == 1.0


@needs_data
def test_partial_set_is_refused_as_a_baseline(tmp_path):
    import json

    from evals.agent_eval.cases import EVALSET
    data = json.loads(EVALSET.read_text(encoding="utf-8"))
    data["eval_cases"] = data["eval_cases"][:10]
    p = tmp_path / "partial.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SystemExit):
        load_cases(p)
    assert len(load_cases(p, strict=False)) == 10


# --- one case ----------------------------------------------------------------

def test_perfect_record_passes_everything():
    s = score_case(make_case(), perfect(make_case()))
    assert s["event_type"]["ok"]
    assert all(t["status_ok"] for t in s["topics"])
    assert s["topics"][0]["code_ok"]
    assert {f["field"]: f["outcome"] for f in s["fields"]} == {
        "U-01": "TP", "U-02": "TN", "U-04": "TP", "MH-01": "TN"}


def test_derived_u03_is_not_scored_as_a_field():
    s = score_case(make_case(), perfect(make_case()))
    assert "U-03" not in {f["field"] for f in s["fields"]}


def test_no_record_staged_fails_every_item():
    s = score_case(make_case(), None)
    assert not s["staged"]
    assert not s["event_type"]["ok"]
    assert [t["actual"] for t in s["topics"]] == [NOT_STAGED, NOT_STAGED]
    assert not any(t["status_ok"] for t in s["topics"])


def test_omitted_planned_topic_counts_as_not_discussed():
    case = make_case()
    args = perfect(case)
    args["topics"] = args["topics"][:1]  # the not-discussed topic left out
    s = score_case(case, args)
    assert s["topics"][1]["actual"] == NOT_DISCUSSED and s["topics"][1]["status_ok"]


def test_topic_labels_match_ignoring_case_and_spacing():
    case = make_case()
    args = perfect(case)
    args["topics"][0]["topic"] = "  ranges "
    assert score_case(case, args)["topics"][0]["status_ok"]


def test_duplicate_rows_fail_topic_status_and_disposition():
    case = make_case()
    args = perfect(case)
    args["topics"].append({"topic": "Ranges", "discussed": True, "disposition_code": 1})
    t = score_case(case, args)["topics"][0]
    assert t["actual"] == DUPLICATE and not t["status_ok"] and not t["code_ok"]


def test_off_plan_rows_are_reported():
    case = make_case()
    args = perfect(case)
    args["topics"].append({"topic": "Range hoods", "discussed": True, "disposition_code": 1})
    s = score_case(case, args)
    assert s["off_plan"] == ["Range hoods"]
    assert all(t["status_ok"] for t in s["topics"])


def test_wrong_disposition_code():
    case = make_case()
    args = perfect(case)
    args["topics"][0]["disposition_code"] = 8
    t = score_case(case, args)["topics"][0]
    assert t["status_ok"] and not t["code_ok"]
    assert (t["expected_code"], t["actual_code"]) == (1, 8)


def test_code_given_as_string_still_matches():
    case = make_case()
    args = perfect(case)
    args["topics"][0]["disposition_code"] = "1"
    assert score_case(case, args)["topics"][0]["code_ok"]


def test_discussed_topic_marked_not_discussed_fails():
    case = make_case()
    args = perfect(case)
    args["topics"][0]["discussed"] = False
    t = score_case(case, args)["topics"][0]
    assert t["actual"] == NOT_DISCUSSED and not t["status_ok"] and not t["code_ok"]


def test_no_person_mentioned_means_on_site_visit():
    # Approved rule: a person -> Meeting, otherwise On-site visit. The key's
    # null ("no person, no call") is scored as On-site visit.
    case = make_case(event_type=None)
    assert score_case(case, {"event_type": "On-site visit"})["event_type"]["ok"]
    assert not score_case(case, {"event_type": "Meeting"})["event_type"]["ok"]


def test_contested_event_type_is_still_skipped():
    case = make_case(event_type=None, contested=frozenset({"event_type"}))
    assert score_case(case, {"event_type": "Meeting"})["event_type"] is None


def test_contested_items_are_skipped():
    case = make_case(contested=frozenset({"event_type", "Ranges", "U-01"}))
    s = score_case(case, None)
    assert s["event_type"] is None
    assert [t["topic"] for t in s["topics"]] == ["Q3 Paint, Primer"]
    assert "U-01" not in {f["field"] for f in s["fields"]}


def test_agent_without_must_capture_misses_every_stated_field():
    s = score_case(make_case(), perfect(make_case(), with_fields=False))
    assert not s["fields_captured"]
    assert {f["field"]: f["outcome"] for f in s["fields"]} == {
        "U-01": "FN", "U-02": "TN", "U-04": "FN", "MH-01": "TN"}


def test_filling_a_not_stated_field_is_fabrication():
    case = make_case()
    args = perfect(case)
    args["must_capture"]["U-02"] = "spoke with target"
    args["must_capture"]["MH-01"] = "not stated"  # an explicit "not stated" is not a value
    out = {f["field"]: f["outcome"] for f in score_case(case, args)["fields"]}
    assert out["U-02"] == "FP" and out["MH-01"] == "TN"


def test_captured_but_wrong_value():
    case = make_case()
    args = perfect(case)
    args["must_capture"]["U-04"] = "order placed: $500"
    f = next(f for f in score_case(case, args)["fields"] if f["field"] == "U-04")
    assert f["outcome"] == "TP" and f["value_ok"] is False


@pytest.mark.parametrize("expected,actual,ok", [
    ("12 units", "12 units a month", True),
    ("Quote created: $3000", "quote created $3000", True),
    ("Bill", "Bob", False),
    ("a", "ab", False),  # too short to count as containment
    ("4 by 4 ft", "4x4 ft", True),  # approved: dimensions stored like 4x4
    ("36 X 48 in", "36x48 in", True),
    ("4x4", "4x6", False),
])
def test_value_agrees(expected, actual, ok):
    assert value_agrees(expected, actual) is ok


# --- rollups -----------------------------------------------------------------

def test_rollup_by_vertical_and_priority():
    a, b = make_case(), make_case(id="HL-001", vertical="HL")
    scores = [score_case(a, perfect(a)), score_case(b, perfect(b, with_fields=False))]
    roll = aggregate(scores, PRIO)
    assert list(roll) == ["all", "HL", "MH"]
    assert roll["MH"]["fields"]["all"]["recall"] == 1.0
    assert roll["HL"]["fields"]["all"]["recall"] == 0.0
    assert roll["all"]["fields"]["P1"]["stated"] == 2  # U-01 in both cases
    assert roll["all"]["fields"]["P3"]["recall"] is None  # MH-01 never stated: n/a, not 0


def test_variance_across_repeats():
    runs = [{"all": {"event_type": {"rate": r}, "topic_status": {"rate": 1.0},
                     "disposition": {"rate": None}, "faithfulness": {"rate": None}}}
            for r in (0.8, 0.9, 1.0)]
    v = variance(runs)
    assert v["event_type"]["mean"] == pytest.approx(0.9)
    assert v["event_type"]["stdev"] == pytest.approx(0.1)
    assert v["topic_status"]["stdev"] == 0.0
    assert "disposition" not in v


def test_scorecard_says_fields_not_captured_and_lists_failures():
    case = make_case()
    args = perfect(case, with_fields=False)
    args["event_type"] = "Phone Call"
    scores = [score_case(case, args)]
    card = scorecard("t", [aggregate(scores, PRIO)], [scores],
                     {"evalset": "x.json", "cases": 1, "judge": None})
    assert "**Not captured.**" in card
    assert "event type: expected 'Meeting', got 'Phone Call'" in card


# --- connection / setup errors -----------------------------------------------

def test_errors_before_any_record_are_not_scored_but_agent_misses_are():
    from evals.agent_eval.run import _score_run, infra_error
    case = make_case()
    dropped = {"id": case.id, "error": "ConnectionClosedError: no close frame", "final": None}
    no_record = {"id": case.id, "final": None}                  # agent never staged: a real miss
    late_drop = {"id": case.id, "error": "ConnectionClosedError", "final": perfect(case)}
    assert infra_error(dropped) and not infra_error(no_record) and not infra_error(late_drop)
    assert _score_run([case], [dropped], judge=None) == []
    assert [s["staged"] for s in _score_run([case], [no_record, late_drop], judge=None)] == [False, True]


def test_scorecard_lists_cases_not_scored_because_of_errors():
    case = make_case()
    scores = [score_case(case, perfect(case))]
    card = scorecard("t", [aggregate(scores, PRIO)], [scores],
                     {"evalset": "x.json", "cases": 2, "judge": None, "infra_errors": [["MH-007"]]})
    assert "Not scored (connection or setup errors" in card and "repeat 1: MH-007" in card


def test_judge_sees_the_reps_scripted_replies_not_just_the_note():
    from evals.agent_eval.run import rep_said
    case = make_case()
    res = {"transcript": [("rep (sent)", case.note), ("agent", "Anything on paint?"),
                          ("rep (sent)", "I didn't get to that on this visit."),
                          ("rep (sent)", "Yes, that's right. Save it.")]}
    said = rep_said(case, res)
    assert said.startswith(case.note)
    assert "Later the rep said: I didn't get to that on this visit." in said
    assert "Anything on paint?" not in said


def test_old_judge_verdicts_are_not_reused():
    from evals.agent_eval.run import _score_run

    class Judge:
        calls = 0

        def check(self, note, staged):
            Judge.calls += 1
            return {"faithful": True, "unsupported": []}

    case = make_case()
    res = {"id": case.id, "final": perfect(case), "transcript": [],
           "judge": {"faithful": False, "unsupported": ["x"]}}          # v1 verdict
    s = _score_run([case], [res], Judge())[0]
    assert Judge.calls == 1 and s["faithful"] is True
    _score_run([case], [res], Judge())                                  # now cached as v2
    assert Judge.calls == 1


def test_a_failed_judge_call_is_not_cached():
    from evals.agent_eval.run import JUDGE_INPUT_VERSION, _score_run

    class Flaky:
        def check(self, note, staged):
            return {"faithful": None, "error": "ConnectTimeout"}

    case = make_case()
    res = {"id": case.id, "final": perfect(case), "transcript": []}
    s = _score_run([case], [res], Flaky())[0]
    assert s["faithful"] is None
    assert res["judge"].get("v") != JUDGE_INPUT_VERSION  # retried next time


# --- the rep's scripted side -------------------------------------------------

def test_missing_topics_drives_the_coverage_reply():
    case = make_case()
    assert missing_topics(case, None) == []
    staged = {"topics": [{"topic": "ranges", "discussed": True}]}
    assert missing_topics(case, staged) == ["Q3 Paint, Primer"]
    staged["topics"].append({"topic": "Q3 Paint, Primer", "discussed": False})
    assert missing_topics(case, staged) == []
    # First staging call: the app does not accept a skip the rep was never asked about.
    assert missing_topics(case, staged, allow_skips=False) == ["Q3 Paint, Primer"]


def test_missing_topics_uses_the_apps_substring_rule():
    case = make_case(planned_topics=["HC Q2 Compact Appliances"])
    staged = {"topics": [{"topic": "Compact Appliances", "discussed": True}]}
    assert missing_topics(case, staged) == []  # covered for the app, so no reminder
