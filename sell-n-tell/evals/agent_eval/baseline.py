"""The committed baseline: aggregate scores only, safe to keep in the repo.

    uv run python -m evals.agent_eval.baseline export evals/runs/full-A evals/runs/full-B evals/runs/full-C --allow-noisy quick:disposition
    uv run python -m evals.agent_eval.baseline show

``export`` reads the scored full runs' scores.json and writes
evals/baselines/golden_v1.json with, for the full set and for the quick
subset, each headline score's mean / min / max / stdev across repeats. No case
ids, notes, names or values -- just numbers -- so it can be committed and
every developer compares against the same reference.

Every ``run.py`` run compares against it automatically; the verdict is in the
run's final_scores.json.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from evals.agent_eval.cases import dataset_sha256, load_cases, load_priorities, quick_subset
from evals.agent_eval.score import aggregate

BASELINE = Path(__file__).resolve().parents[1] / "baselines" / "golden_v1.json"
# How far a score must move to count. The same cases are re-run, so the noise
# that matters is run-to-run model randomness, measured by the baseline's own
# repeats: a change counts when it exceeds 3 x that metric's stdev, and never
# less than DEFAULT_THRESHOLD points (AIML-2702 measured a 1 to 5 point spread).
DEFAULT_THRESHOLD = 5.0
NOISE_MULTIPLIER = 3.0
# A metric whose limit would exceed this is too noisy in that mode to catch
# anything (quick-mode disposition: ~9 topics, limit ~55 points). Leaving it
# out of the verdict is never automatic: ``export`` refuses unless it is named
# with --allow-noisy, the baseline records it under "not_gated", and every run
# lists it as not in the verdict.
MAX_THRESHOLD = 20.0

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


def too_noisy(baseline: dict) -> list[str]:
    """'mode:metric' for every metric whose limit is above MAX_THRESHOLD."""
    return [f"{mode}:{name}" for mode in ("full", "quick")
            for name, m in (baseline.get(mode) or {}).items() if threshold_for(m) > MAX_THRESHOLD]


def not_gated(baseline: dict, allow_noisy: list[str] = ()) -> dict[str, list[str]]:
    """The metrics to leave out of the verdict, per mode. Refuses any too-noisy
    metric that was not explicitly allowed, so a noisy re-export can never
    quietly drop a metric from the gate."""
    noisy = too_noisy(baseline)
    unexpected = sorted(set(noisy) - set(allow_noisy))
    if unexpected:
        raise SystemExit(
            f"too noisy to gate (limit above {MAX_THRESHOLD:.0f} points): {', '.join(unexpected)}. "
            "Add more runs, or leave it out of the verdict deliberately with "
            + " ".join(f"--allow-noisy {m}" for m in unexpected))
    out: dict[str, list[str]] = {}
    for item in noisy:
        mode, name = item.split(":", 1)
        out.setdefault(mode, []).append(name)
    return out


def export(run_dirs: list[Path] | Path, out: Path = BASELINE, allow_noisy: list[str] = ()) -> dict:
    """From one or more scored full runs (each may hold several repeats)."""
    run_dirs = [run_dirs] if isinstance(run_dirs, Path) else list(run_dirs)
    repeats, metas = [], []
    key = dataset_sha256()
    for d in run_dirs:
        # The baseline is stamped with the current key, so every run in it
        # must have been scored on that key (re-score an older run first).
        final = d / "final_scores.json"
        scored_on = json.loads(final.read_text(encoding="utf-8")).get("dataset_sha256") if final.exists() else None
        if scored_on != key:
            raise SystemExit(f"{d}: scored on a different golden set than the current one "
                             f"({str(scored_on)[:8]} vs {key[:8]}); re-score it first")
        data = json.loads((d / "scores.json").read_text(encoding="utf-8"))
        metas.append(data["meta"])
        repeats += data["cases"]
    if any(len(r) < 80 for r in repeats):
        raise SystemExit("a baseline needs full runs (90 cases); one of these runs is partial")
    priorities = load_priorities()
    quick_ids = {c.id for c in quick_subset(load_cases())}
    full = [aggregate(scores, priorities) for scores in repeats]
    quick = [aggregate([s for s in scores if s["id"] in quick_ids], priorities) for scores in repeats]
    baseline = {
        "evalset": metas[0]["evalset"],
        # A re-scored run lives in <run>/rescore-<mode>/: name the run, not the subfolder.
        "source_run": ", ".join(f"{d.parent.name}/{d.name}" if d.name.startswith("rescore-") else d.name
                                for d in run_dirs),
        "repeats": len(repeats),
        "judge": metas[0].get("judge"),
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_sha256": key,
        "min_threshold_points": DEFAULT_THRESHOLD,
        "noise_multiplier": NOISE_MULTIPLIER,
        "full": summarise(full),
        "quick": summarise(quick),
    }
    baseline["not_gated"] = not_gated(baseline, allow_noisy)  # refuses before anything is written
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, indent=1) + "\n", encoding="utf-8")
    return baseline


def threshold_for(ref_metric: dict) -> float:
    return max(DEFAULT_THRESHOLD, NOISE_MULTIPLIER * ref_metric.get("stdev", 0.0))


def compare(rollups: list[dict], baseline: dict, mode: str,
            skip: list[str] = ()) -> tuple[list[str], list[str]]:
    """(report lines, regressed metric names) for a run against the baseline.
    ``skip`` lists metrics shown but left out of the verdict; so are the
    baseline's recorded "not_gated" metrics for this mode."""
    ref = baseline.get(mode) or {}
    noisy = set((baseline.get("not_gated") or {}).get(mode, []))
    now = summarise(rollups)
    lines = [f"## Against the baseline ({mode} set, run '{baseline.get('source_run')}')", "",
             "| metric | baseline | this run | change | counts if beyond | verdict |",
             "|---|---|---|---|---|---|"]
    regressed = []
    for name, _read, higher in METRICS:
        if name not in ref or name not in now:
            continue
        b, c = ref[name]["mean"], now[name]["mean"]
        delta, limit = c - b, threshold_for(ref[name])
        worse = -delta if higher else delta
        if name in skip:
            verdict = "not judged (too many judge failures)"
        elif name in noisy:
            verdict = f"not judged (too noisy in {mode} mode)"
        elif worse > limit:
            verdict = "REGRESSION"
            regressed.append(name)
        elif -worse > limit:
            verdict = "improved"
        else:
            verdict = "same (within noise)"
        lines.append(f"| {name} | {b:.1f}% | {c:.1f}% | {delta:+.1f} | ±{limit:.1f} | {verdict} |")
    return lines, regressed


def load(path: Path = BASELINE) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Export or show the committed baseline.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write evals/baselines/golden_v1.json from a scored run")
    ex.add_argument("run_dirs", type=Path, nargs="+", help="one or more full runs")
    ex.add_argument("--allow-noisy", action="append", default=[], metavar="MODE:METRIC",
                    help=f"leave a metric whose limit is above {MAX_THRESHOLD:.0f} points out of "
                         "the verdict, e.g. quick:disposition (repeatable)")
    sub.add_parser("show", help="print the committed baseline")
    args = ap.parse_args()
    if args.cmd == "export":
        b = export(args.run_dirs, allow_noisy=args.allow_noisy)
        print(f"written: {BASELINE}")
    else:
        b = load()
        if b is None:
            raise SystemExit(f"no baseline at {BASELINE}")
    for mode in ("full", "quick"):
        print(f"\n{mode}:")
        for name, m in b[mode].items():
            print(f"  {name:<20} {m['mean']:6.1f}%  (range {m['min']:.1f} to {m['max']:.1f}, {m['runs']} runs)")
    for mode, names in (b.get("not_gated") or {}).items():
        print(f"\nnot in the {mode} verdict (too noisy): {', '.join(names)}")


if __name__ == "__main__":
    main()
