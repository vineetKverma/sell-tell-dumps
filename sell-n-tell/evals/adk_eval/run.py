"""Run the golden set through ADK's evaluation framework (adk eval, live mode).

    uv run --with "google-adk[eval]==2.10.0" --with google-cloud-aiplatform python -m evals.adk_eval.run quick
    uv run --with "google-adk[eval]==2.10.0" --with google-cloud-aiplatform python -m evals.adk_eval.run full

Unlike ``evals.agent_eval`` (which drives the running app over its WebSocket),
this loads the agent in-process and lets ADK's LocalEvalService drive it in
live mode: each golden note is sent as the rep's turn, ADK records the tool
calls, and scores them with

  - our custom metrics (evals/adk_eval/metrics.py): event type, topic status,
    disposition, P1 field recall, fields not invented -- the same rules as
    the WebSocket harness; and
  - ADK's built-in judge ``rubric_based_tool_use_quality_v1``, with rubrics
    for grounded summaries, no invented skip reasons and topic marking.

One live session at a time (AgentEvaluator always opens 4 in parallel, which
timed out on the opening handshake). A case whose live session fails is
retried once, then reported and left out of the scores.

Needs ADK with live evaluation (2.10 here; the project pins an older version
-- hence ``--with`` until it upgrades).

Writes evals/runs/adk-<mode>-<time>/summary.json: per-metric means and the
per-case scores (case ids and numbers only).
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name("eval_config.json")
RUNS = ROOT / "evals" / "runs"
APP_NAME = "voice-notes-logger"
LIVE_PARALLELISM = 1     # live sessions at once
JUDGE_PARALLELISM = 4    # metric evaluations at once (judge calls)


def _quiet_library_warnings() -> None:
    """ADK labels its eval classes [EXPERIMENTAL] and imports a deprecated
    vertexai module internally; both print on every run and say nothing about
    the eval. Hide just those, so the per-case progress is readable."""
    import warnings
    warnings.filterwarnings("ignore", message=r"\[EXPERIMENTAL\]", category=UserWarning)
    warnings.filterwarnings("ignore", message=r".*vertexai\.preview\.rag.*", category=UserWarning)


def _prepare_app_env() -> None:
    """Same settings the app uses, and the app folder on the import path so
    the agent module imports the way main.py imports it."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / "app" / ".env")
    sys.path.insert(0, str(ROOT / "app"))


def _preflight(config) -> None:
    """Fail in seconds, not after the run: every custom metric must import."""
    missing = []
    for name, c in (config.custom_metrics or {}).items():
        module, fn = c.code_config.name.rsplit(".", 1)
        try:
            if not callable(getattr(importlib.import_module(module), fn)):
                missing.append(f"{name}: {c.code_config.name} is not callable")
        except (ImportError, AttributeError) as exc:
            missing.append(f"{name}: {c.code_config.name} ({exc})")
    if missing:
        here = Path(__file__).resolve().parent
        pkg = sys.modules.get("evals.adk_eval")
        raise SystemExit(
            "Custom metrics not found:\n  " + "\n  ".join(missing)
            + f"\n\nrun.py is in:          {here}"
            + f"\nfiles next to it:      {sorted(p.name for p in here.iterdir() if p.is_file())}"
            + f"\nmetrics.py next to it: {(here / 'metrics.py').exists()}"
            + f"\nevals.adk_eval loaded from: {list(getattr(pkg, '__path__', []))}"
            + "\nmetrics.py must sit next to run.py in evals/adk_eval/.")


def build_eval_set(mode: str):
    from google.adk.evaluation.eval_set import EvalSet

    from evals.agent_eval.cases import EVALSET, load_cases, quick_subset

    data = json.loads(EVALSET.read_text(encoding="utf-8"))
    if mode == "quick":
        keep = {c.id for c in quick_subset(load_cases())}
        data["eval_cases"] = [c for c in data["eval_cases"] if c["eval_id"] in keep]
    return EvalSet.model_validate(data)


def summarise(case_scores: dict[str, dict[str, float | None]], failed: list[str],
              rates: set[str] | None = None) -> dict:
    """Mean per metric over the cases it applied to (None = not evaluated).

    ``rates`` are the metrics scored 0..1 (our criteria); they are shown as
    percentages. Anything else -- ADK adds efficiency metrics such as
    inference_call_count_v1 on its own -- is a count, shown as a plain average."""
    by_metric: dict[str, list[float]] = defaultdict(list)
    for scores in case_scores.values():
        for metric, value in scores.items():
            if value is not None:
                by_metric[metric].append(value)
    metrics = {}
    for m, v in sorted(by_metric.items()):
        if rates is None or m in rates:
            metrics[m] = {"mean": round(statistics.fmean(v) * 100, 1), "unit": "%", "cases": len(v)}
        else:
            metrics[m] = {"mean": round(statistics.fmean(v), 2), "unit": "per case", "cases": len(v)}
    return {
        "cases_scored": len(case_scores),
        "connection_failures": failed,
        "metrics": metrics,
        "per_case": case_scores,
    }


async def _run(eval_set, config) -> tuple[dict, list[str]]:
    from google.adk.evaluation.base_eval_service import (
        EvaluateConfig,
        EvaluateRequest,
        InferenceConfig,
        InferenceRequest,
        InferenceStatus,
    )
    from google.adk.evaluation.eval_config import get_eval_metrics_from_config
    from google.adk.evaluation.in_memory_eval_sets_manager import InMemoryEvalSetsManager
    from google.adk.evaluation.local_eval_service import LocalEvalService
    from google.adk.evaluation.metric_evaluator_registry import (
        DEFAULT_METRIC_EVALUATOR_REGISTRY,
        register_custom_metrics_from_config,
    )
    from google.adk.evaluation.simulation.user_simulator_provider import UserSimulatorProvider
    from voice_notes_agent.agent import root_agent

    sets = InMemoryEvalSetsManager()
    sets.create_eval_set(app_name=APP_NAME, eval_set_id=eval_set.eval_set_id)
    for case in eval_set.eval_cases:
        sets.add_eval_case(app_name=APP_NAME, eval_set_id=eval_set.eval_set_id, eval_case=case)
    service = LocalEvalService(
        root_agent=root_agent, eval_sets_manager=sets,
        metric_evaluator_registry=register_custom_metrics_from_config(
            config, DEFAULT_METRIC_EVALUATOR_REGISTRY.fork()),
        user_simulator_provider=UserSimulatorProvider(user_simulator_config=config.user_simulator_config))
    live = InferenceConfig(use_live=True, parallelism=LIVE_PARALLELISM,
                           live_timeout_seconds=config.live_model_config.timeout_seconds)

    async def infer(case_ids=None):
        out = []
        request = InferenceRequest(app_name=APP_NAME, eval_set_id=eval_set.eval_set_id,
                                   eval_case_ids=case_ids, inference_config=live)
        async for result in service.perform_inference(inference_request=request):
            ok = result.status == InferenceStatus.SUCCESS
            print(f"  {result.eval_case_id}  {'ok' if ok else 'FAILED: ' + str(result.error_message)[:120]}",
                  flush=True)
            out.append(result)
        return out

    results = await infer()
    failed = [r.eval_case_id for r in results if r.status != InferenceStatus.SUCCESS]
    if failed:  # one retry for live sessions that failed to open or complete
        print(f"retrying {len(failed)} case(s)")
        retried = {r.eval_case_id: r for r in await infer(failed)}
        results = [retried.get(r.eval_case_id, r) for r in results]
        failed = [r.eval_case_id for r in results if r.status != InferenceStatus.SUCCESS]

    good = [r for r in results if r.status == InferenceStatus.SUCCESS]
    print(f"scoring {len(good)} case(s)", flush=True)
    case_scores: dict[str, dict[str, float | None]] = {}
    request = EvaluateRequest(inference_results=good, evaluate_config=EvaluateConfig(
        eval_metrics=get_eval_metrics_from_config(config), parallelism=JUDGE_PARALLELISM))
    async for case_result in service.evaluate(evaluate_request=request):
        case_scores[case_result.eval_id] = {m.metric_name: m.score
                                            for m in case_result.overall_eval_metric_results}
    return case_scores, failed


def main() -> None:
    ap = argparse.ArgumentParser(description="Score the agent with ADK's eval framework (live mode).")
    ap.add_argument("mode", choices=("quick", "full"))
    args = ap.parse_args()

    _quiet_library_warnings()
    _prepare_app_env()
    from google.adk.evaluation.eval_config import EvalConfig

    config = EvalConfig.model_validate(json.loads(CONFIG.read_text(encoding="utf-8")))
    if config.live_model_config is None:
        raise SystemExit("This ADK version has no live evaluation; run with a newer ADK (see the docstring).")
    _preflight(config)
    eval_set = build_eval_set(args.mode)
    out = RUNS / f"adk-{args.mode}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    print(f"adk eval ({args.mode}): {len(eval_set.eval_cases)} cases, live mode, one session at a time, "
          f"agent model {os.getenv('VOICE_NOTES_AGENT_MODEL', 'default')}")

    case_scores, failed = asyncio.run(_run(eval_set, config))
    summary = summarise(case_scores, failed, rates=set(config.criteria))
    summary.update(mode=args.mode, framework="adk eval (LocalEvalService)", run=out.name)
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"\n{'metric':<36} {'mean':>10}  cases")
    for m, v in summary["metrics"].items():
        shown = f"{v['mean']:.1f}%" if v["unit"] == "%" else f"{v['mean']:.2f}/case"
        print(f"{m:<36} {shown:>10}  {v['cases']}")
    if failed:
        print(f"\nnot scored (live session failed twice): {', '.join(failed)}")
    print(f"\nwritten: {out / 'summary.json'}")


if __name__ == "__main__":
    main()
