"""Run the golden set through ADK's evaluation framework (adk eval, live mode).

    uv run --with "google-adk[eval]==2.10.0" python -m evals.adk_eval.run quick
    uv run --with "google-adk[eval]==2.10.0" python -m evals.adk_eval.run full

Unlike ``evals.agent_eval`` (which drives the running app over its WebSocket),
this loads the agent in-process and lets ADK drive it in live mode: each
golden note is sent as the rep's turn, ADK records the tool calls, and scores
them with

  - our custom metrics (evals/adk_eval/metrics.py): event type, topic status,
    disposition, P1 field recall, fields not invented -- the same rules as
    the WebSocket harness; and
  - ADK's built-in judge ``rubric_based_tool_use_quality_v1``, with rubrics
    for grounded summaries, no invented skip reasons and topic marking.

Needs ADK with live evaluation and custom metrics (2.10 here; the version
pinned in uv.lock may be older -- hence ``--with`` until the project upgrades).

Writes evals/runs/adk-<mode>-<time>/: results.csv (ADK's per-case rows; it
quotes notes, so it stays git-ignored) and summary.json (per-metric means,
numbers only).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
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


def _prepare_app_env() -> None:
    """Same settings the app uses, and the app folder on the import path so
    ADK can import the agent module the way main.py does."""
    from dotenv import load_dotenv
    load_dotenv(ROOT / "app" / ".env")
    sys.path.insert(0, str(ROOT / "app"))


def build_eval_set(mode: str):
    from google.adk.evaluation.eval_set import EvalSet

    from evals.agent_eval.cases import EVALSET, load_cases, quick_subset

    data = json.loads(EVALSET.read_text(encoding="utf-8"))
    if mode == "quick":
        keep = {c.id for c in quick_subset(load_cases())}
        data["eval_cases"] = [c for c in data["eval_cases"] if c["eval_id"] in keep]
    return EvalSet.model_validate(data)


def summarise_csv(path: Path) -> dict:
    """Mean score per metric over the cases it applied to (NOT_EVALUATED rows,
    e.g. disposition on a case with no discussed topic, are left out)."""
    scores: dict[str, list[float]] = defaultdict(list)
    cases: set[str] = set()
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            cases.add(row["eval_id"])
            if row.get("eval_status") != "NOT_EVALUATED" and row.get("score") not in ("", "None", None):
                scores[row["metric_name"]].append(float(row["score"]))
    return {"cases": len(cases),
            "metrics": {m: {"mean": round(statistics.fmean(v) * 100, 1), "cases_scored": len(v)}
                        for m, v in sorted(scores.items())}}


def main() -> None:
    ap = argparse.ArgumentParser(description="Score the agent with ADK's eval framework (live mode).")
    ap.add_argument("mode", choices=("quick", "full"))
    args = ap.parse_args()

    _prepare_app_env()
    from google.adk.evaluation.agent_evaluator import AgentEvaluator
    from google.adk.evaluation.eval_config import EvalConfig

    eval_set = build_eval_set(args.mode)
    config = EvalConfig.model_validate(json.loads(CONFIG.read_text(encoding="utf-8")))
    out = RUNS / f"adk-{args.mode}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True)
    results = out / "results.csv"
    print(f"adk eval ({args.mode}): {len(eval_set.eval_cases)} cases, live mode, "
          f"agent model {os.getenv('VOICE_NOTES_AGENT_MODEL', 'default')}")

    try:
        asyncio.run(AgentEvaluator.evaluate_eval_set(
            agent_module="voice_notes_agent", eval_set=eval_set, eval_config=config,
            num_runs=1, print_detailed_results=False, output_file=str(results)))
    except AssertionError:
        pass  # thresholds are 0 (report-only); ADK still asserts on any case it could not score

    if not results.exists():
        raise SystemExit("ADK produced no results file -- see the errors above.")
    summary = summarise_csv(results)
    summary.update(mode=args.mode, framework="adk eval", run=out.name)
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"\n{'metric':<36} {'mean':>7}  cases")
    for m, v in summary["metrics"].items():
        print(f"{m:<36} {v['mean']:>6.1f}%  {v['cases_scored']}")
    print(f"\nwritten: {out}")


if __name__ == "__main__":
    main()
