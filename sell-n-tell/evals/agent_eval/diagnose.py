"""Where do the baseline's misses come from? Counts only by default -- no
note text (``--show-unsupported`` is the exception, below).

    uv run python -m evals.agent_eval.diagnose evals/runs/baseline
    uv run python -m evals.agent_eval.diagnose evals/runs/extract-<time>/scores_topup.json

Reads scores.json from a scored run and breaks each headline metric into
expected -> actual pairs, so a systematic pattern (e.g. the agent marking
planned topics as discussed when the note never names them) is told apart
from scattered errors. ``--show-unsupported N`` also prints N of the judge's
unsupported statements; those quote the agent's summaries, so keep them on
this machine.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description="Break the baseline's misses down by pattern.")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--show-unsupported", type=int, default=0, metavar="N")
    args = ap.parse_args()
    path = args.run_dir if args.run_dir.is_file() else args.run_dir / "scores.json"
    if not path.exists() and (args.run_dir / "scores_golden.json").exists():
        path = args.run_dir / "scores_golden.json"     # an extract_eval run (one file per set)
    data = json.loads(path.read_text(encoding="utf-8"))
    runs = data["cases"]
    errors = data["meta"].get("infra_errors")
    print(f"repeats: {len(runs)}  scored cases per repeat: {[len(r) for r in runs]}  "
          + (f"not scored (errors): {[len(x) for x in errors]}" if errors is not None
             else "errors: see the run's summary.json (an extract run counts them there)"))

    ev, topic, code, faith = Counter(), Counter(), Counter(), Counter()
    unsupported: list[str] = []
    topics_per_case = Counter()
    for scores in runs:
        for s in scores:
            if s["event_type"]:
                e = s["event_type"]
                ev[(e["expected"], e["actual"])] += 1
            for t in s["topics"]:
                topic[(t["expected"], t["actual"])] += 1
                if "code_ok" in t and t["actual"] == "discussed":
                    code[(t["expected_code"], t["actual_code"])] += 1
            topics_per_case[len(s["topics"])] += 1
            if s["faithful"] is not None:
                faith[s["faithful"]] += 1
                unsupported += s.get("unsupported") or []

    def table(title, counter, top=12):
        total = sum(counter.values())
        print(f"\n## {title} (total {total})")
        for (exp, act), n in counter.most_common(top):
            mark = "  " if exp == act else "x "
            print(f"  {mark}{n:>5}  {n / total:6.1%}  expected {exp!s:<16} -> got {act}")

    table("Event type", ev)
    table("Topic status", topic)
    table("Disposition code (topics the agent called discussed)", code)
    print(f"\n## Faithfulness  faithful: {faith[True]}  not faithful: {faith[False]}")
    if unsupported:
        kinds = Counter()
        for u in unsupported:
            low = u.lower()
            kinds["mentions not getting to / skipping a topic" if any(
                k in low for k in ("did not get", "didn't get", "not discussed", "did not discuss",
                                   "skipp", "time constraint", "not covered", "no time",
                                   "out of time", "ran out", "didn't have time", "did not have time")) else
                  "other"] += 1
        print("  unsupported statements by kind: " + ", ".join(f"{k}: {n}" for k, n in kinds.items()))
    for u in unsupported[: args.show_unsupported]:
        print(f"  - {u}")


if __name__ == "__main__":
    main()
