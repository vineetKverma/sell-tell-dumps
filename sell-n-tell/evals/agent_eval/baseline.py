"""The committed baseline: aggregate scores only, safe to keep in the repo.

    uv run python -m evals.agent_eval.baseline export evals/runs/baseline
    uv run python -m evals.agent_eval.baseline show

``export`` reads a scored run's scores.json and writes
evals/baselines/golden_v1.json with, for the full set and for the --quick
subset, each headline score's mean / min / max / stdev across repeats. No case
ids, notes, names or values -- just numbers -- so it can be committed and
every developer compares against the same reference.

``run.py --compare`` reads it and reports each score against it.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from evals.agent_eval.cases import load_cases, load_priorities, quick_subset
from evals.agent_eval.score import aggregate

BASELINE = Path(__file__).resolve().parents[1] / "baselines" / "golden_v1.json"
# A score must fall by more than this many points (or the invented-value rate
# rise by more) to count as a regression. AIML-2702 measured the run-to-run
# spread at 1 to 5 points, so smaller moves are noise.
DEFAULT_THRESHOLD = 5.0

# (name, how to read it from a rollup, higher_is_better)
METRICS = [
    ("event_type", lambda r: r["event_type"]["rate"], True),
    ("topic_status", lambda r: r["topic_status"]["rate"], True),
    ("disposition", lambda r: r["disposition"]["rate"], True),
    ("faithfulness", lambda r: r["faithfulness"]["rate"], True),
    ("field_recall_P1", lambda r: r["fields"].get("P1", {}).get("recall"), True),
    ("field_recall_all", lambda r: r["fields"]["all"]["recall"], True),
    ("field_invented_rate", lambda r: r["fields"]["all"]["fabrication"], False),
]


def summarise(rollups: list[dict]) -> dict:
    """Per metric across repeats (group 'all'): mean/min/max/stdev in percent."""
    out = {}
    for name, read, higher in METRICS:
        vals = [read(r["all"]) for r in rollups]
        vals = [v * 100 for v in vals if v is not None]
        if vals:
            out[name] = {"mean": round(statistics.fmean(vals), 2), "min": round(min(vals), 2),
                         "max": round(max(vals), 2),
                         "stdev": round(statistics.stdev(vals), 2) if len(vals) > 1 else 0.0,
                         "runs": len(vals), "higher_is_better": higher}
    return out


def export(run_dir: Path, out: Path = BASELINE) -> dict:
    data = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    priorities = load_priorities()
    quick_ids = {c.id for c in quick_subset(load_cases())}
    full = [aggregate(scores, priorities) for scores in data["cases"]]
    quick = [aggregate([s for s in scores if s["id"] in quick_ids], priorities) for scores in data["cases"]]
    baseline = {
        "evalset": data["meta"]["evalset"],
        "source_run": run_dir.name,
        "judge": data["meta"].get("judge"),
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "threshold_points": DEFAULT_THRESHOLD,
        "full": summarise(full),
        "quick": summarise(quick),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, indent=1) + "\n", encoding="utf-8")
    return baseline


def compare(rollups: list[dict], baseline: dict, mode: str,
            threshold: float = DEFAULT_THRESHOLD) -> tuple[list[str], list[str]]:
    """(report lines, regressed metric names) for a run against the baseline."""
    ref = baseline.get(mode) or {}
    now = summarise(rollups)
    lines = [f"## Against the baseline ({mode} set, run '{baseline.get('source_run')}', "
             f"regression = worse by more than {threshold:g} points)", "",
             "| metric | baseline | this run | change | verdict |", "|---|---|---|---|---|"]
    regressed = []
    for name, _read, higher in METRICS:
        if name not in ref or name not in now:
            continue
        b, c = ref[name]["mean"], now[name]["mean"]
        delta = c - b
        worse = -delta if higher else delta
        if worse > threshold:
            verdict = "REGRESSION"
            regressed.append(name)
        elif -worse > threshold:
            verdict = "improved"
        else:
            verdict = "same (within noise)"
        lines.append(f"| {name} | {b:.1f}% | {c:.1f}% | {delta:+.1f} | {verdict} |")
    return lines, regressed


def load(path: Path = BASELINE) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Export or show the committed baseline.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write evals/baselines/golden_v1.json from a scored run")
    ex.add_argument("run_dir", type=Path)
    sub.add_parser("show", help="print the committed baseline")
    args = ap.parse_args()
    if args.cmd == "export":
        b = export(args.run_dir)
        print(f"written: {BASELINE}")
    else:
        b = load()
        if b is None:
            raise SystemExit(f"no baseline at {BASELINE}")
    for mode in ("full", "quick"):
        print(f"\n{mode}:")
        for name, m in b[mode].items():
            print(f"  {name:<20} {m['mean']:6.1f}%  (range {m['min']:.1f} to {m['max']:.1f}, {m['runs']} runs)")


if __name__ == "__main__":
    main()
