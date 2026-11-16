"""Disposition, topic by topic, between two sets of runs (agent or extract) --
read-only, ids and codes only, no note text, no model calls.

    cd <repo>
    uv run python C:\\tmp\\disposition_paired.py --old <agent run> ... --new <extract run> ...

A run is a folder under evals/runs/ holding scores.json (an agent run or a
re-score folder) or scores_golden.json (an extract run). Repeats at
temperature 0 are near-identical, so the honest sample is the topics, not
topics x repeats: each topic counts once, right when most of its repeats are.

Prints, per set: codes right over all repeats, by the key's code (99 / a real
code), what answering 99 every time would score, and topics right by
majority. Then the paired table over the topics both sets scored, with an
exact two-sided sign (McNemar) test on the topics where they differ.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from math import comb
from pathlib import Path

RUNS = Path("evals") / "runs"
NONE_FITS = 99


def repeats(run: str) -> list[list[tuple[str, str, object, bool]]]:
    """Per repeat: (case id, topic, expected code, right) for every scored code."""
    folder = Path(run) if Path(run).exists() else RUNS / run
    path = next((folder / f for f in ("scores.json", "scores_golden.json") if (folder / f).exists()), None)
    if path is None:
        raise SystemExit(f"{run}: no scores.json or scores_golden.json")
    return [[(s["id"], t["topic"], t.get("expected_code"), bool(t["code_ok"]))
             for s in cases if s for t in s["topics"] if "code_ok" in t]
            for cases in json.loads(path.read_text(encoding="utf-8"))["cases"]]


def summarise(runs: list[str]) -> dict:
    per_topic: dict[tuple[str, str], list[bool]] = defaultdict(list)
    want: dict[tuple[str, str], object] = {}
    for run in runs:
        for rep in repeats(run):
            for cid, topic, expected, ok in rep:
                per_topic[(cid, topic)].append(ok)
                want[(cid, topic)] = expected
    if not per_topic:
        raise SystemExit(f"no scored codes in {', '.join(runs)} (an extract run needs --dispositions)")
    return {"per_topic": per_topic, "want": want}


def pct(right: int, of: int) -> str:
    return f"{right}/{of} = {100 * right / of:.1f}%" if of else "n/a"


def majority(v: list[bool]) -> bool:
    return sum(v) * 2 > len(v)


def report(label: str, s: dict) -> None:
    topics, want = s["per_topic"], s["want"]
    is_99 = lambda k: str(want[k]) == str(NONE_FITS)  # noqa: E731
    flat = [(k, ok) for k, v in topics.items() for ok in v]
    k99 = [ok for k, ok in flat if is_99(k)]
    real = [ok for k, ok in flat if not is_99(k)]
    print(f"{label}: {len(next(iter(topics.values())))} repeats, {len(topics)} topics")
    print(f"  all repeats:        {pct(sum(ok for _, ok in flat), len(flat))}")
    print(f"  key says 99:        {pct(sum(k99), len(k99))}")
    print(f"  key says real code: {pct(sum(real), len(real))}")
    print(f"  always answer 99:   {pct(len(k99), len(flat))}")
    print(f"  topics right by majority: {pct(sum(majority(v) for v in topics.values()), len(topics))}")
    unstable = sum(0 < sum(v) < len(v) for v in topics.values())
    print(f"  topics that differ between repeats: {unstable} of {len(topics)}")


def sign_test(b: int, c: int) -> float:
    """Exact two-sided p for b against c discordant topics (binomial, p = 0.5)."""
    n, k = b + c, min(b, c)
    return 1.0 if n == 0 else min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def main() -> None:
    ap = argparse.ArgumentParser(description="Disposition topic by topic between two sets of runs.")
    ap.add_argument("--old", nargs="+", required=True)
    ap.add_argument("--new", nargs="+", required=True)
    args = ap.parse_args()
    old, new = summarise(args.old), summarise(args.new)
    report("old", old)
    report("new", new)
    shared = sorted(set(old["per_topic"]) & set(new["per_topic"]))
    o = {k: majority(old["per_topic"][k]) for k in shared}
    n = {k: majority(new["per_topic"][k]) for k in shared}
    both = sum(o[k] and n[k] for k in shared)
    only_new = [k for k in shared if n[k] and not o[k]]
    only_old = [k for k in shared if o[k] and not n[k]]
    neither = sum(not o[k] and not n[k] for k in shared)
    print(f"\npaired over {len(shared)} shared topics (right by majority):")
    print(f"  both right {both} | only new right {len(only_new)} | only old right {len(only_old)} | both wrong {neither}")
    print(f"  exact two-sided sign test on the {len(only_new) + len(only_old)} that differ: "
          f"p = {sign_test(len(only_new), len(only_old)):.3f}")
    print("  only new right: " + "; ".join(f"{c} {t}" for c, t in only_new))
    print("  only old right: " + "; ".join(f"{c} {t}" for c, t in only_old))


if __name__ == "__main__":
    main()
