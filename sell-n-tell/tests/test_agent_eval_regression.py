"""Quick subset, committed baseline and regression verdicts. No model, no network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evals.agent_eval import baseline as bl  # noqa: E402
from evals.agent_eval.cases import EVALSET, Case, quick_subset  # noqa: E402

needs_data = pytest.mark.skipif(not EVALSET.exists(), reason="golden eval data not present")


def _case(cid, vertical):
    return Case(id=cid, vertical=vertical, note="n", planned_topics=["t"], event_type="Meeting",
                topics=[], fields={})


def test_quick_subset_is_fixed_and_balanced():
    cases = [_case(f"{v}-{i:03d}", v) for v in ("MH", "HL") for i in (5, 1, 3, 2, 4)]
    picked = quick_subset(cases)
    assert [c.id for c in picked] == ["HL-001", "HL-002", "HL-003", "MH-001", "MH-002", "MH-003"]
    assert quick_subset(list(reversed(cases))) == picked  # order of input does not matter


@needs_data
def test_quick_subset_of_the_golden_set_is_18_cases():
    from evals.agent_eval.cases import load_cases
    picked = quick_subset(load_cases())
    assert len(picked) == 18 and {c.vertical for c in picked} == {"MH", "HS", "HL", "IS", "TR", "IN"}


def _rollup(event, topic, faith, recall, fab):
    acc = lambda r: {"rate": r, "ok": 0, "n": 1}  # noqa: E731
    return {"all": {"event_type": acc(event), "topic_status": acc(topic), "disposition": acc(None),
                    "faithfulness": acc(faith),
                    "fields": {"all": {"recall": recall, "fabrication": fab}, "P1": {"recall": recall}}}}


BASE = {"source_run": "baseline", "full": bl.summarise([_rollup(0.60, 0.49, 0.22, 0.0, 0.0)] * 3)}


def test_baseline_summary_holds_numbers_only():
    s = BASE["full"]
    assert s["event_type"] == {"mean": 60.0, "min": 60.0, "max": 60.0, "stdev": 0.0, "runs": 3,
                               "higher_is_better": True}
    assert "disposition" not in s  # no rate -> not reported, never 0
    text = json.dumps(BASE)
    assert "HL-" not in text and "note" not in text


def test_small_moves_are_noise_and_big_drops_are_regressions():
    same = [_rollup(0.62, 0.47, 0.24, 0.0, 0.0)]
    lines, regressed = bl.compare(same, BASE, "full")
    assert regressed == [] and any("within noise" in l for l in lines)

    worse = [_rollup(0.50, 0.49, 0.22, 0.0, 0.0)]
    _, regressed = bl.compare(worse, BASE, "full")
    assert regressed == ["event_type"]


def test_more_invented_values_is_a_regression_fewer_is_not():
    _, regressed = bl.compare([_rollup(0.60, 0.49, 0.22, 0.30, 0.10)], BASE, "full")
    assert regressed == ["field_invented_rate"]          # invented rate rose 10 points
    _, regressed = bl.compare([_rollup(0.60, 0.70, 0.22, 0.30, 0.0)], BASE, "full")
    assert regressed == []                               # improvements never fail


def test_compare_skips_a_mode_the_baseline_does_not_have():
    lines, regressed = bl.compare([_rollup(0.1, 0.1, 0.1, 0.0, 0.0)], BASE, "quick")
    assert regressed == [] and len(lines) == 4  # header only
