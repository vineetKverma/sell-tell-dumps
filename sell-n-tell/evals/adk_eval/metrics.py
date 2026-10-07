"""Our scores as ADK custom metrics, so `adk eval` reports them natively.

ADK calls each function with the actual invocations (what the agent did) and
the expected ones (from golden_v1.evalset.json). The agent's whole record is
the arguments of its last ``stage_visit_notes`` call, and the expected
invocation carries the answer key (event type, topics, must-capture fields,
contested items), so each metric rebuilds a Case and reuses the harness's
scorer -- the same rules as ``evals/agent_eval``, one source of truth.

Every metric returns a score in [0, 1], higher is better. A case with nothing
to score for a metric (e.g. no discussed topic for disposition) is
NOT_EVALUATED, never 0.
"""

from __future__ import annotations

from typing import Optional

from google.adk.evaluation.eval_case import ConversationScenario, Invocation, get_all_tool_calls
from google.adk.evaluation.eval_metrics import EvalMetric, EvalStatus
from google.adk.evaluation.evaluator import EvaluationResult, PerInvocationResult

from evals.agent_eval.cases import Case, load_priorities
from evals.agent_eval.score import score_case

STAGE_TOOL = "stage_visit_notes"
_PRIORITIES: dict[str, int] | None = None


def _priorities() -> dict[str, int]:
    global _PRIORITIES
    if _PRIORITIES is None:
        _PRIORITIES = load_priorities()
    return _PRIORITIES


def _text(content) -> str:
    return "".join(p.text or "" for p in (content.parts or [])) if content else ""


def _last_stage_args(invocations: list[Invocation]) -> dict | None:
    calls = [c for inv in invocations for c in get_all_tool_calls(inv.intermediate_data)
             if c.name == STAGE_TOOL]
    return dict(calls[-1].args or {}) if calls else None


def case_from_expected(expected: list[Invocation]) -> Case:
    """The answer key, as the expected stage_visit_notes call carries it."""
    args = _last_stage_args(expected) or {}
    fields = dict(args.get("must_capture") or {})
    vertical = next((f.split("-")[0] for f in fields if not f.startswith("U-")), "?")
    topics = list(args.get("topics") or [])
    return Case(id="adk", vertical=vertical, note=_text(expected[0].user_content),
                planned_topics=[t["topic"] for t in topics], event_type=args.get("event_type"),
                topics=topics, fields=fields, contested=frozenset(args.get("contested") or []))


def _result(score: Optional[float], actual: list[Invocation], expected: list[Invocation]) -> EvaluationResult:
    status = EvalStatus.NOT_EVALUATED if score is None else EvalStatus.PASSED
    per = [PerInvocationResult(actual_invocation=actual[-1], expected_invocation=expected[-1],
                               score=score, eval_status=status)] if actual else []
    return EvaluationResult(overall_score=score, overall_eval_status=status, per_invocation_results=per)


def _scored(actual: list[Invocation], expected: Optional[list[Invocation]]) -> dict | None:
    if not expected:
        return None
    return score_case(case_from_expected(expected), _last_stage_args(actual))


def _rate(ok: int, n: int) -> Optional[float]:
    return ok / n if n else None


def event_type_accuracy(eval_metric: EvalMetric, actual: list[Invocation],
                        expected: Optional[list[Invocation]] = None,
                        conversation_scenario: Optional[ConversationScenario] = None) -> EvaluationResult:
    s = _scored(actual, expected)
    e = s and s["event_type"]
    return _result(None if not e else float(e["ok"]), actual, expected or [])


def topic_status_accuracy(eval_metric: EvalMetric, actual: list[Invocation],
                          expected: Optional[list[Invocation]] = None,
                          conversation_scenario: Optional[ConversationScenario] = None) -> EvaluationResult:
    s = _scored(actual, expected)
    topics = s["topics"] if s else []
    return _result(_rate(sum(t["status_ok"] for t in topics), len(topics)), actual, expected or [])


def disposition_accuracy(eval_metric: EvalMetric, actual: list[Invocation],
                         expected: Optional[list[Invocation]] = None,
                         conversation_scenario: Optional[ConversationScenario] = None) -> EvaluationResult:
    s = _scored(actual, expected)
    coded = [t for t in (s["topics"] if s else []) if "code_ok" in t]
    return _result(_rate(sum(t["code_ok"] for t in coded), len(coded)), actual, expected or [])


def field_recall_p1(eval_metric: EvalMetric, actual: list[Invocation],
                    expected: Optional[list[Invocation]] = None,
                    conversation_scenario: Optional[ConversationScenario] = None) -> EvaluationResult:
    s = _scored(actual, expected)
    stated = [f for f in (s["fields"] if s else [])
              if _priorities().get(f["field"]) == 1 and f["outcome"] in ("TP", "FN")]
    return _result(_rate(sum(f["outcome"] == "TP" for f in stated), len(stated)), actual, expected or [])


def field_not_invented(eval_metric: EvalMetric, actual: list[Invocation],
                       expected: Optional[list[Invocation]] = None,
                       conversation_scenario: Optional[ConversationScenario] = None) -> EvaluationResult:
    """Share of not-stated fields the agent correctly left empty (1 - invented rate)."""
    s = _scored(actual, expected)
    unstated = [f for f in (s["fields"] if s else []) if f["outcome"] in ("TN", "FP")]
    return _result(_rate(sum(f["outcome"] == "TN" for f in unstated), len(unstated)), actual, expected or [])
