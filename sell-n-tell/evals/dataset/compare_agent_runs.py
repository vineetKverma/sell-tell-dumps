"""Where two sets of agent runs differ, case by case. Counts and case ids only.

    uv run python -m evals.dataset.compare_agent_runs --old <run> <run> <run> --new <run> <run>

Reads each run's scores.json (evals/runs/<run>/). For topic status and the
summary judge, lists the cases that got worse from the old runs to the new
ones (per-run average, so sets of different sizes compare), with the kind of
topic miss: "discussed -> not discussed" is a missed topic, "not discussed ->
discussed" an over-claim. Scattered ids point to noise; a cluster points to a
cause.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

RUNS = Path(__file__).resolve().parents[1] / "runs"


def tally(runs: list[str]) -> tuple[Counter, Counter, dict[str, Counter]]:
    topic_misses, unfaithful, kinds = Counter(), Counter(), {}
    for run in runs:
        cases = json.loads((RUNS / run / "scores.json").read_text(encoding="utf-8"))["cases"][0]
        for s in cases:
            bad = [t for t in s["topics"] if not t["status_ok"]]
            topic_misses[s["id"]] += len(bad)
            unfaithful[s["id"]] += s.get("faithful") is False
            kinds.setdefault(s["id"], Counter()).update(f"{t['expected']} -> {t['actual']}" for t in bad)
    return topic_misses, unfaithful, kinds


def worse(old: Counter, new: Counter, n_old: int, n_new: int) -> list[tuple[str, float, float]]:
    return [(i, old[i] / n_old, new[i] / n_new) for i in sorted(set(old) | set(new))
            if new[i] / n_new - old[i] / n_old >= 0.5]


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare two sets of agent runs case by case.")
    ap.add_argument("--old", nargs="+", required=True, help="run folder names (evals/runs/...)")
    ap.add_argument("--new", nargs="+", required=True)
    args = ap.parse_args()
    (ot, of, _), (nt, nf, nk) = tally(args.old), tally(args.new)
    o, n = len(args.old), len(args.new)

    print(f"Topic-status misses per run, old ({o} runs) -> new ({n} runs), cases that got worse:")
    for i, a, b in worse(ot, nt, o, n):
        print(f"  {i}: {a:.1f} -> {b:.1f}   new runs: {dict(nk[i])}")
    print(f"\nUnfaithful summaries per run, cases that got worse:")
    for i, a, b in worse(of, nf, o, n):
        print(f"  {i}: {a:.1f} -> {b:.1f}")
    print(f"\nCases that got better: topic status {len(worse(nt, ot, n, o))}, summaries {len(worse(nf, of, n, o))}")
    print(f"Totals per run -- topic misses: {sum(ot.values()) / o:.1f} -> {sum(nt.values()) / n:.1f};"
          f" unfaithful summaries: {sum(of.values()) / o:.1f} -> {sum(nf.values()) / n:.1f}")


if __name__ == "__main__":
    main()
