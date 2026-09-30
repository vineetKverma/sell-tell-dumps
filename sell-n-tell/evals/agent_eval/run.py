"""Run the golden eval set against the live agent and write the scorecard.

Start the app first (the same way you would for the smoke test), then:

    uv run python -m evals.agent_eval.run --name baseline
    uv run python -m evals.agent_eval.run --name baseline --repeat 3 --judge
    uv run python -m evals.agent_eval.run --name try --cases HL-001,MH-004
    uv run python -m evals.agent_eval.run --rescore evals/runs/baseline --judge

Writes evals/runs/<name>/ (git-ignored -- it holds customer notes):
  run<k>.jsonl     per case: the staged record, whether it was committed,
                   tool errors, and the full transcript
  scores.json      every per-item outcome plus the rollups
  scorecard.md     per vertical and overall, fields by priority, variance
                   across repeats, and every failure as expected vs actual
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from evals.agent_eval.cases import EVALSET, load_cases, load_priorities
from evals.agent_eval.score import aggregate, score_case, variance

RUNS = Path(__file__).resolve().parents[1] / "runs"


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1%}"


def _acc(a: dict) -> str:
    return "n/a" if not a["n"] else f"{_pct(a['rate'])} ({a['ok']}/{a['n']})"


def scorecard(name: str, runs: list[dict], per_case: list[list[dict]], meta: dict) -> str:
    last = runs[-1]
    lines = [f"# Eval scorecard: {name}", "",
             f"eval set: `{meta['evalset']}`  cases: {meta['cases']}  repeats: {len(runs)}  "
             f"judge: {meta['judge'] or 'off'}", ""]

    lines += ["## Overall and per vertical" + (" (last repeat)" if len(runs) > 1 else ""), "",
              "| group | cases | not staged | event type | topic status | disposition "
              "| duplicate rows | off-plan rows | faithfulness |",
              "|---|---|---|---|---|---|---|---|---|"]
    for g, r in last.items():
        lines.append(f"| {g} | {r['cases']} | {r['not_staged']} | {_acc(r['event_type'])} "
                     f"| {_acc(r['topic_status'])} | {_acc(r['disposition'])} "
                     f"| {r['duplicate_rows']} | {r['off_plan_rows']} | {_acc(r['faithfulness'])} |")

    allr = last["all"]
    lines += ["", "## Must-capture fields by priority", ""]
    if not allr["fields_captured"]:
        lines += ["**Not captured.** The agent's `stage_visit_notes` call has no "
                  "`must_capture` argument yet, so every stated field counts as missed. "
                  "Recall below is the gap the vertical build has to close.", ""]
    lines += ["| priority | stated in notes | captured | recall | precision | fabrication | value accuracy |",
              "|---|---|---|---|---|---|---|"]
    for p, f in allr["fields"].items():
        lines.append(f"| {p} | {f['stated']} | {f['tp']} | {_pct(f['recall'])} | {_pct(f['precision'])} "
                     f"| {_pct(f['fabrication'])} | {_pct(f['value_accuracy'])} |")
    lines += ["", "<details><summary>Per field</summary>", "",
              "| field | stated | recall | precision | fabrication |", "|---|---|---|---|---|"]
    for fid, f in allr["per_field"].items():
        lines.append(f"| {fid} | {f['stated']} | {_pct(f['recall'])} | {_pct(f['precision'])} "
                     f"| {_pct(f['fabrication'])} |")
    lines += ["", "</details>", ""]

    if len(runs) > 1:
        lines += ["## Run-to-run variance (overall)", "",
                  "| metric | runs | mean | min | max | stdev |", "|---|---|---|---|---|---|"]
        for m, v in variance(runs).items():
            lines.append(f"| {m} | {v['runs']} | {_pct(v['mean'])} | {_pct(v['min'])} "
                         f"| {_pct(v['max'])} | {v['stdev']:.3f} |")
        lines.append("")

    lines += ["## Failures (last repeat): expected vs actual", ""]
    fails = _failures(per_case[-1])
    lines += fails or ["none"]
    return "\n".join(lines) + "\n"


def _failures(scores: list[dict]) -> list[str]:
    out = []
    for s in scores:
        items = []
        if not s["staged"]:
            items.append("never staged a record")
        if s["event_type"] and not s["event_type"]["ok"]:
            items.append(f"event type: expected {s['event_type']['expected']!r}, got {s['event_type']['actual']!r}")
        for t in s["topics"]:
            if not t["status_ok"]:
                items.append(f"topic {t['topic']!r}: expected {t['expected']}, got {t['actual']}")
            elif t.get("code_ok") is False:
                items.append(f"topic {t['topic']!r}: expected code {t['expected_code']}, got {t['actual_code']}")
        if s["off_plan"]:
            items.append(f"off-plan rows: {s['off_plan']}")
        for f in s["fields"]:
            if f["outcome"] == "FP":
                items.append(f"{f['field']}: not stated, agent filled {f['actual']!r}")
            elif f.get("value_ok") is False:
                items.append(f"{f['field']}: expected {f['expected']!r}, got {f['actual']!r}")
        if s["faithful"] is False:
            items.append(f"summary not faithful: {s.get('unsupported')}")
        if items:
            out.append(f"- **{s['id']}**: " + "; ".join(items))
    return out


def _score_run(cases, results: list[dict], judge) -> list[dict]:
    by_id = {c.id: c for c in cases}
    scores = []
    for res in results:
        case = by_id[res["id"]]
        s = score_case(case, res.get("final"))
        if judge and res.get("final"):
            verdict = res.get("judge") or judge.check(case.note, res["final"])
            res["judge"] = verdict
            s["faithful"] = verdict.get("faithful")
            s["unsupported"] = verdict.get("unsupported")
        elif res.get("judge"):
            s["faithful"] = res["judge"].get("faithful")
            s["unsupported"] = res["judge"].get("unsupported")
        scores.append(s)
    return scores


async def _drive(cases, base_url: str, log) -> list[dict]:
    from evals.agent_eval.drive import run_case  # needs websockets; not for --rescore

    results = []
    for i, case in enumerate(cases, 1):
        t0 = time.monotonic()
        res = await run_case(case, base_url)
        results.append(res)
        state = res.get("error") or ("committed" if res["committed"] else
                                     "staged" if res["final"] else "NOT STAGED")
        log(f"  [{i}/{len(cases)}] {case.id}  {state}  ({time.monotonic() - t0:.0f}s)")
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description="Run and score the golden eval set.")
    ap.add_argument("--name", help="run name; output goes to evals/runs/<name>/")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--evalset", type=Path, default=EVALSET,
                    help="another eval set, e.g. the field top-up (default: golden_v1)")
    ap.add_argument("--cases", help="comma-separated case ids (a trial run; not a baseline)")
    ap.add_argument("--repeat", type=int, default=1, help="run the set N times to measure variance")
    ap.add_argument("--judge", action="store_true", help="score summary faithfulness (model calls)")
    ap.add_argument("--judge-model", default=None)
    ap.add_argument("--rescore", type=Path, help="re-score a saved run instead of running the agent")
    args = ap.parse_args()

    # golden_v1 must be complete to count as a baseline; other sets only need
    # unique ids (checked in load_cases).
    cases = load_cases(args.evalset, strict=args.evalset == EVALSET)
    priorities = load_priorities()
    judge = None
    if args.judge:
        from evals.agent_eval.judge import DEFAULT_MODEL, Judge
        judge = Judge(model=args.judge_model or DEFAULT_MODEL)

    if args.rescore:
        out = args.rescore
        raw_runs = [[json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
                    for p in sorted(out.glob("run*.jsonl"))]
        if not raw_runs:
            raise SystemExit(f"no run*.jsonl in {out}")
        name = out.name
    else:
        if not args.name:
            raise SystemExit("--name is required (or use --rescore)")
        if args.cases:
            wanted = {c.strip() for c in args.cases.split(",") if c.strip()}
            unknown = wanted - {c.id for c in cases}
            if unknown:
                raise SystemExit(f"unknown case ids: {sorted(unknown)}")
            cases = [c for c in cases if c.id in wanted]
        name, out = args.name, RUNS / args.name
        if out.exists():
            raise SystemExit(f"{out} exists -- pick a new --name, or --rescore it")
        out.mkdir(parents=True)
        raw_runs = []
        for k in range(1, args.repeat + 1):
            print(f"repeat {k}/{args.repeat}: {len(cases)} cases against {args.base_url}")
            results = asyncio.run(_drive(cases, args.base_url, print))
            _write_jsonl(out / f"run{k}.jsonl", results)
            raw_runs.append(results)

    ran = {r["id"] for r in raw_runs[0]}
    cases = [c for c in cases if c.id in ran]
    per_case = [_score_run(cases, results, judge) for results in raw_runs]
    if judge:  # keep the verdicts so a later --rescore does not pay for them again
        for k, results in enumerate(raw_runs, 1):
            _write_jsonl(out / f"run{k}.jsonl", results)
    rollups = [aggregate(s, priorities) for s in per_case]
    meta = {"evalset": args.evalset.name, "cases": len(cases), "judge": judge and judge.model,
            "full_set": args.evalset == EVALSET and len(cases) == 90, "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "scores.json").write_text(json.dumps(
        {"meta": meta, "runs": rollups, "variance": variance(rollups), "cases": per_case},
        indent=1, default=str) + "\n", encoding="utf-8")
    card = scorecard(name, rollups, per_case, meta)
    (out / "scorecard.md").write_text(card, encoding="utf-8")
    print(card.split("## Failures")[0])
    print(f"written: {out}")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


if __name__ == "__main__":
    main()
