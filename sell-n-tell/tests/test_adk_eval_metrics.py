"""The ADK custom metrics and config, on hand-built invocations. No model, no network."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

pytest.importorskip("google.adk.evaluation.eval_case")
from google.adk.evaluation.eval_config import EvalConfig as _EvalConfig  # noqa: E402

# The ADK bridge needs custom metrics and live evaluation; older ADK versions
# (the project may pin one) have neither, so skip instead of failing there.
if not {"custom_metrics", "live_model_config"} <= set(_EvalConfig.model_fields):
    pytest.skip("installed ADK has no custom metrics / live evaluation", allow_module_level=True)

from google.adk.evaluation.eval_case import IntermediateData, Invocation  # noqa: E402
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus  # noqa: E402
from google.genai import types  # noqa: E402

from evals.adk_eval import metrics as m  # noqa: E402
from evals.agent_eval.cases import EVALSET  # noqa: E402

TOPICS = [{"topic": "Ranges", "discussed": True, "disposition_code": 1},
          {"topic": "Q3 Paint, Primer", "discussed": False, "disposition_code": None}]
KEY = {"event_type": "Meeting", "topics": TOPICS, "contested": [],
       "must_capture": {"U-01": "Bill | | unknown", "U-02": None, "MH-01": None, "U-03": "x"}}


def inv(args: dict | None, text: str = "Met Bill, quoted ranges.") -> Invocation:
    calls = [types.FunctionCall(name="stage_visit_notes", args=args)] if args is not None else []
    return Invocation(user_content=types.Content(role="user", parts=[types.Part(text=text)]),
                      intermediate_data=IntermediateData(tool_uses=calls))


EXPECTED = [inv(KEY)]
METRIC = EvalMetric(metric_name="x", threshold=0.0)


def score(fn, actual_args):
    return fn(METRIC, [inv(actual_args)], EXPECTED)


@pytest.fixture(autouse=True)
def fixed_priorities(monkeypatch):
    monkeypatch.setattr(m, "_PRIORITIES", {"U-01": 1, "U-02": 1, "MH-01": 2})


def test_perfect_record_scores_one_everywhere():
    actual = {"event_type": "Meeting", "topics": TOPICS[:1], "must_capture": {"U-01": "Bill | | unknown"}}
    for fn in (m.event_type_accuracy, m.topic_status_accuracy, m.disposition_accuracy,
               m.field_recall_p1, m.field_not_invented):
        r = score(fn, actual)
        assert r.overall_score == 1.0 and r.overall_eval_status == EvalStatus.PASSED, fn.__name__


def test_wrong_answers_lower_the_scores():
    actual = {"event_type": "On-site visit",
              "topics": [{"topic": "Ranges", "discussed": True, "disposition_code": 8},
                         {"topic": "Q3 Paint, Primer", "discussed": True, "disposition_code": 1}],
              "must_capture": {"U-02": "spoke with target"}}
    assert score(m.event_type_accuracy, actual).overall_score == 0.0
    assert score(m.topic_status_accuracy, actual).overall_score == 0.5
    assert score(m.disposition_accuracy, actual).overall_score == 0.0
    assert score(m.field_recall_p1, actual).overall_score == 0.0     # U-01 stated, missed
    assert score(m.field_not_invented, actual).overall_score == 0.5  # U-02 invented, MH-01 left empty


def test_no_stage_call_fails_and_nothing_to_score_is_not_evaluated():
    assert m.topic_status_accuracy(METRIC, [inv(None)], EXPECTED).overall_score == 0.0
    no_codes = [inv(dict(KEY, topics=[TOPICS[1]]))]
    r = m.disposition_accuracy(METRIC, [inv({"topics": []})], no_codes)
    assert r.overall_score is None and r.overall_eval_status == EvalStatus.NOT_EVALUATED


def test_the_last_stage_call_is_the_one_scored():
    first = types.FunctionCall(name="stage_visit_notes", args={"event_type": "Phone Call", "topics": []})
    last = types.FunctionCall(name="stage_visit_notes", args={"event_type": "Meeting", "topics": TOPICS[:1]})
    actual = [Invocation(user_content=types.Content(role="user", parts=[types.Part(text="n")]),
                         intermediate_data=IntermediateData(tool_uses=[first, last]))]
    assert m.event_type_accuracy(METRIC, actual, EXPECTED).overall_score == 1.0


def test_contested_items_are_skipped():
    expected = [inv(dict(KEY, contested=["event_type", "Ranges"]))]
    assert m.event_type_accuracy(METRIC, [inv({"event_type": "Phone Call"})], expected).overall_score is None
    r = m.topic_status_accuracy(METRIC, [inv({"topics": []})], expected)
    assert r.overall_score == 1.0  # only the not-discussed topic is scored


def test_config_parses_and_every_custom_metric_resolves():
    from google.adk.evaluation.eval_config import EvalConfig
    cfg_path = Path(_ROOT) / "evals" / "adk_eval" / "eval_config.json"
    cfg = EvalConfig.model_validate(json.loads(cfg_path.read_text(encoding="utf-8")))
    assert cfg.live_model_config is not None
    assert set(cfg.custom_metrics) <= set(cfg.criteria)
    for name, c in cfg.custom_metrics.items():
        module, fn = c.code_config.name.rsplit(".", 1)
        assert callable(getattr(importlib.import_module(module), fn)), name


@pytest.mark.skipif(not EVALSET.exists(), reason="golden eval data not present")
def test_eval_sets_build_for_both_modes():
    from evals.adk_eval.run import build_eval_set
    assert len(build_eval_set("full").eval_cases) == 90
    quick = build_eval_set("quick")
    assert len(quick.eval_cases) == 18
    assert all(c.session_input and c.session_input.state.get("planned_topics") for c in quick.eval_cases)
