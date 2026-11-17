"""Why the agent's disposition moves between identical full runs -- read-only,
no model calls.

    cd <repo>
    uv run python C:\\tmp\\agent_flips.py full-A full-B full-C [--notes]

For every topic the key says was discussed (the disposition items), and every
not-discussed topic any run claimed, prints what each run saved:
    a code       discussed, with that code
    ND           saved as not discussed
    --           left out of the record
    DUP          two rows for it
and, per run, how the record was reached: stage calls, and whether the
scripted rep had to answer the coverage reminder ("I didn't get to that").

Then the misses split by cause, per run, and the arithmetic of the noise
limit. For topics that differ between runs it prints each run's topic
summary, and with --notes the case's note, so the reason can be read.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
RUNS = Path("evals") / "runs"
COVERAGE_REPLY = "I didn't get to that on this visit."


def load(run: str):
    folder = Path(run) if Path(run).exists() else RUNS / run
    scores = json.loads((folder / "scores.json").read_text(encoding="utf-8"))["cases"][0]
    raw = {}
    for line in (folder / "run1.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            raw[r["id"]] = r
    return {s["id"]: s for s in scores}, raw


def norm(t):
    return " ".join(str(t or "").lower().split())


def shown(t: dict) -> str:
    a = t["actual"]
    if a == "discussed":
        return str(t.get("actual_code"))
    return {"not discussed": "ND", "duplicate rows": "DUP", "not staged": "NS"}.get(a, a[:3])


def row_of(raw: dict, case_id: str, topic: str) -> dict:
    final = (raw.get(case_id) or {}).get("final") or {}
    for t in final.get("topics") or []:
        if isinstance(t, dict) and norm(t.get("topic")) == norm(topic):
            return t
    return {}


def label(t: dict | None, raw: dict, cid: str, title: str) -> str:
    if t is None:
        return "?"
    s = shown(t)
    if t["actual"] == "discussed" and "actual_code" not in t:  # over-claimed: the scorer keeps no code
        s = str(row_of(raw, cid, title).get("disposition_code"))
    return "--" if s == "ND" and not row_of(raw, cid, title) else s


def coverage_rounds(raw: dict, case_id: str) -> int:
    lines = (raw.get(case_id) or {}).get("transcript") or []
    return sum(1 for who, text in lines if who == "rep (sent)" and text.startswith(COVERAGE_REPLY))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--notes", action="store_true", help="also print the note of each case that differs")
    args = ap.parse_args()
    runs = [load(r) for r in args.runs]
    n = len(runs)

    ids = sorted(set().union(*(s.keys() for s, _ in runs)))
    disc, over = [], []
    for cid in ids:
        per = [s.get(cid) for s, _ in runs]
        titles = [t["topic"] for t in (per[0] or {}).get("topics", [])]
        for i, title in enumerate(titles):
            items = [next((t for t in (p or {}).get("topics", []) if t["topic"] == title), None) for p in per]
            if items[0] is None:
                continue
            if "code_ok" in items[0]:
                disc.append((cid, title, items))
            elif any(t and t["actual"] == "discussed" for t in items):
                over.append((cid, title, items))

    def kind(items):
        ok = [bool(t and t.get("code_ok")) for t in items]
        return "ok" if all(ok) else "WRONG" if not any(ok) else "FLIP"

    print(f"== the {len(disc)} disposition items (key says discussed) ==")
    print(f"{'case':7} {'key':>4}  " + "  ".join(f"run{i+1:<3}" for i in range(n)) + "  cov.rounds  kind   topic")
    for cid, title, items in disc:
        cov = "/".join(str(coverage_rounds(raw, cid)) for _, raw in runs)
        print(f"{cid:7} {items[0]['expected_code']:>4}  "
              + "  ".join(f"{label(t, runs[r][1], cid, title):<6}" for r, t in enumerate(items))
              + f"  {cov:<10}  {kind(items):5}  {title[:45]}")

    print(f"\n== not-discussed topics claimed in some run ({len(over)}) ==")
    for cid, title, items in over:
        cov = "/".join(str(coverage_rounds(raw, cid)) for _, raw in runs)
        print(f"{cid:7}  " + "  ".join(f"{label(t, runs[r][1], cid, title):<6}" for r, t in enumerate(items)) + f"  {cov:<10}  {title[:45]}")

    print("\n== disposition misses by cause, per run ==")
    for r in range(n):
        c = Counter()
        for cid, title, items in disc:
            t = items[r]
            if t is None or t.get("code_ok"):
                continue
            if t["actual"] == "discussed":
                c["wrong code"] += 1
            elif t["actual"] == "not discussed":
                c["not discussed" + (" (after the coverage reply)" if coverage_rounds(runs[r][1], cid) else "")] += 1
            else:
                c[t["actual"]] += 1
        right = sum(1 for _, _, items in disc if items[r] and items[r].get("code_ok"))
        print(f"run{r+1}: {right}/{len(disc)} right; misses: {dict(c)}")

    rates = [100 * sum(1 for _, _, it in disc if it[r] and it[r].get("code_ok")) / len(disc) for r in range(n)]
    sd = statistics.stdev(rates) if n > 1 else 0.0
    print(f"\nrates {[round(x, 1) for x in rates]}  stdev {sd:.2f}  limit 3 x stdev = {3*sd:.1f} (gate refuses above 20)")
    k = Counter(kind(it) for _, _, it in disc)
    print(f"items: {k['ok']} right in every run, {k['WRONG']} wrong in every run, {k['FLIP']} differ between runs")

    flips = [(cid, title, it) for cid, title, it in disc if kind(it) == "FLIP"]
    flips += [(cid, title, it) for cid, title, it in over if len({shown(t) for t in it if t}) > 1]
    if not flips:
        return
    print("\n== topics that differ between runs: what each run saved ==")
    notes = {}
    if args.notes:
        from evals.agent_eval.cases import load_cases
        notes = {c.id: c.note for c in load_cases()}
    for cid, title, items in flips:
        key = items[0].get("expected_code", "not discussed")
        print(f"\n-- {cid}  key {key}  {title}")
        if args.notes:
            print(f"   note: {notes.get(cid, '?')}")
        for r, (_, raw) in enumerate(runs):
            t = items[r]
            row = row_of(raw, cid, title)
            stage = (raw.get(cid) or {}).get("stage_calls")
            print(f"   run{r+1}: {label(t, raw, cid, title):<4} stage calls {stage}, coverage rounds "
                  f"{coverage_rounds(raw, cid)}; summary: {(row.get('executive_summary') or '')[:220]}")


if __name__ == "__main__":
    main()
