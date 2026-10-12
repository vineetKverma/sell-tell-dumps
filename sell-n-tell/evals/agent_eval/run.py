"""Score the voice agent on the golden set. Two modes:

    uv run python -m evals.agent_eval.run quick     # 18 cases, about 20 minutes
    uv run python -m evals.agent_eval.run full      # 90 cases, about 1.5 hours

The app is started automatically if nothing answers on --base-url. Every run
writes evals/runs/<mode>-<time>/ (git-ignored -- it quotes customer notes):

  final_scores.json  the verdict (PASS / REGRESSION / INVALID), what was run
                     (app commit, models, dataset checksum), the scores and
                     the comparison with the committed baseline. Numbers only.
  scorecard.md       the same, plus every miss as expected vs actual
  scores.json        every per-item outcome
  run1.jsonl         per case: the saved record and the full transcript,
                     appended as each case finishes

Exit code: 0 PASS, 1 REGRESSION, 2 INVALID (the run can't be trusted).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from evals.agent_eval.baseline import compare as compare_to_baseline
from evals.agent_eval.baseline import load as load_baseline
from evals.agent_eval.baseline import summarise
from evals.agent_eval.cases import (
    EVALSET,
    dataset_sha256,
    load_cases,
    load_priorities,
    quick_subset,
)
from evals.agent_eval.judge import DEFAULT_MODEL as JUDGE_MODEL
from evals.agent_eval.judge import Judge
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
    skipped = meta.get("infra_errors") or []
    if any(skipped):
        lines += ["**Not scored (connection or setup errors, not agent behaviour):** "
                  + "; ".join(f"repeat {k}: {', '.join(ids)}" for k, ids in enumerate(skipped, 1) if ids)
                  + ". They were already retried once; if this persists, check the app log and run again.", ""]

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


# Bumped whenever what the judge is shown changes, so verdicts made from the
# old input are re-judged instead of reused. v2: the rep's scripted replies
# ("I didn't get to that ...") are included -- v1 showed only the note, and
# every summary repeating a reply was wrongly marked as invented.
JUDGE_INPUT_VERSION = 2


def rep_said(case, res: dict) -> str:
    """Everything the rep side said: the note, then each scripted reply."""
    replies = [text for who, text in res.get("transcript") or []
               if who == "rep (sent)" and text != case.note]
    return "\n".join([case.note, *(f"Later the rep said: {t}" for t in replies)])


def infra_error(res: dict) -> bool:
    """The run broke before the agent produced anything -- a dropped socket,
    a session that could not be created. That says nothing about the agent,
    so the case is retried once automatically and, if it fails again, left
    out of the scores. An error AFTER the agent staged a record is still scored:
    the record exists."""
    return bool(res.get("error")) and not res.get("final")


def _score_run(cases, results: list[dict], judge) -> list[dict]:
    by_id = {c.id: c for c in cases}
    scores = []
    for res in results:
        if infra_error(res):
            continue
        case = by_id[res["id"]]
        s = score_case(case, res.get("final"))
        if judge and res.get("final"):
            cached = res.get("judge") if res.get("judge", {}).get("v") == JUDGE_INPUT_VERSION else None
            if cached is None:
                print(f"  judging {res['id']} ...", flush=True)
            verdict = cached or judge.check(rep_said(case, res), res["final"])
            if verdict.get("faithful") is not None:  # a failed call is retried on the next --rescore
                verdict["v"] = JUDGE_INPUT_VERSION
            else:
                print(f"    not judged: {verdict.get('error', '')[:120]}", flush=True)
            res["judge"] = verdict
            s["faithful"] = verdict.get("faithful")
            s["unsupported"] = verdict.get("unsupported")
        elif res.get("judge", {}).get("v") == JUDGE_INPUT_VERSION:
            s["faithful"] = res["judge"].get("faithful")
            s["unsupported"] = res["judge"].get("unsupported")
        scores.append(s)
    return scores


async def _drive(cases, base_url: str, log, sink: Path | None = None) -> list[dict]:
    """Run each case in turn. With ``sink``, each result is appended to that
    file as soon as it finishes, so a crash or Ctrl-C keeps what was done."""
    from evals.agent_eval.drive import run_case  # needs websockets; not for --rescore

    results = []
    for i, case in enumerate(cases, 1):
        t0 = time.monotonic()
        res = await run_case(case, base_url)
        results.append(res)
        if sink is not None:
            with sink.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
        state = res.get("error") or ("committed" if res["committed"] else
                                     "staged" if res["final"] else "NOT STAGED")
        log(f"  [{i}/{len(cases)}] {case.id}  {state}  ({time.monotonic() - t0:.0f}s)")
    return results


MODES = ("quick", "full")
# A run where more than this share of cases hit connection/setup errors (even
# after one automatic retry) says too little about the agent to judge.
MAX_INFRA_ERROR_RATE = 0.10
# The same for the judge: above this share of unjudged summaries, faithfulness
# is reported but left out of the verdict.
MAX_UNJUDGED_RATE = 0.10


def _git_commit() -> str:
    root = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "app"], cwd=root, capture_output=True,
                               text=True, check=True).stdout.strip()
        return sha + ("+uncommitted-app-changes" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _agent_model() -> str:
    import os

    from dotenv import dotenv_values
    env = dotenv_values(Path(__file__).resolve().parents[2] / "app" / ".env")
    return (os.getenv("VOICE_NOTES_AGENT_MODEL") or env.get("VOICE_NOTES_AGENT_MODEL")
            or "gemini-live-2.5-flash-native-audio")


def final_scores(mode: str, name: str, cases, raw: list[dict], rollup: dict, ref: dict | None) -> dict:
    """The one file every run produces: what was run, whether the run is valid,
    the scores, and the verdict against the baseline. Numbers only."""
    n = len(cases)
    infra = [r["id"] for r in raw if infra_error(r)]
    judged = [r for r in raw if r.get("final") and not infra_error(r)]
    unjudged = sum(1 for r in judged if (r.get("judge") or {}).get("faithful") is None)
    data_hash = dataset_sha256(EVALSET)
    problems = []
    missing = {c.id for c in cases} - {r["id"] for r in raw}
    if missing:  # e.g. --rescore of a run that was stopped part-way
        problems.append(f"{len(missing)} of {n} cases never ran; the run is incomplete")
    if len(infra) > MAX_INFRA_ERROR_RATE * n:
        problems.append(f"{len(infra)} of {n} cases hit connection/setup errors (limit "
                        f"{MAX_INFRA_ERROR_RATE:.0%}); fix the environment and run again")
    skip = []
    if judged and unjudged > MAX_UNJUDGED_RATE * len(judged):
        skip.append("faithfulness")
    excluded = {m: "too many judge failures" for m in skip}
    for m in ((ref or {}).get("not_gated") or {}).get(mode, []):
        excluded[m] = f"too noisy in {mode} mode (recorded in the baseline)"
    comparison, regressed = [], []
    if ref is None:
        problems.append("no committed baseline")
    elif ref.get("dataset_sha256") != data_hash:
        problems.append("the golden set differs from the one the baseline was made on")
    elif not problems:
        comparison, regressed = compare_to_baseline([rollup], ref, mode, skip=skip)
    verdict = "INVALID" if problems else ("REGRESSION" if regressed else "PASS")
    return {
        "verdict": verdict,
        "problems": problems,
        "regressed": regressed,
        "mode": mode, "run": name,
        "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "app_commit": _git_commit(),
        "agent_model": _agent_model(),
        "judge_model": JUDGE_MODEL,
        "dataset": EVALSET.name, "dataset_sha256": data_hash,
        "cases": n, "scored": n - len(infra) - len(missing), "connection_errors": infra,
        "unjudged_summaries": unjudged,
        "excluded_from_verdict": excluded,
        "scores": summarise([rollup]),
        "baseline_run": ref and ref.get("source_run"),
        "comparison": comparison,
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Score the voice agent on the golden set: 'quick' (18 cases) or 'full' (90).")
    ap.add_argument("mode", choices=MODES)
    ap.add_argument("--base-url", default="http://localhost:8000",
                    help="the app; started automatically if nothing answers there")
    ap.add_argument("--rescore", type=Path, help=argparse.SUPPRESS)  # maintainers: re-score a saved run
    args = ap.parse_args()

    all_cases = load_cases(EVALSET)
    cases = quick_subset(all_cases) if args.mode == "quick" else all_cases
    priorities = load_priorities()
    judge = Judge(model=JUDGE_MODEL)

    if args.rescore:
        out = args.rescore
        wanted = {c.id for c in cases}  # e.g. `quick --rescore` of a full run scores its quick cases
        raw = [r for r in read_run(out / "run1.jsonl") if r.get("id") in wanted]
        name = out.name
    else:
        name = f"{args.mode}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        out = RUNS / name
        out.mkdir(parents=True)
        with app_running(args.base_url, start=not _healthy(args.base_url)):
            from evals.agent_eval.drive import SessionEndpointError
            print(f"{args.mode}: {len(cases)} cases against {args.base_url}")
            try:
                raw = asyncio.run(_drive(cases, args.base_url, print, sink=out / "run1.jsonl"))
                redo = [i for i, r in enumerate(raw) if infra_error(r)]
                if redo:  # one automatic retry for connection/setup errors
                    print(f"retrying {len(redo)} case(s) that hit connection errors")
                    by_id = {c.id: c for c in cases}
                    fresh = asyncio.run(_drive([by_id[raw[i]["id"]] for i in redo], args.base_url, print))
                    for i, res in zip(redo, fresh, strict=True):
                        raw[i] = res
            except SessionEndpointError as exc:  # exit 2: the run can't measure anything
                print(f"VERDICT: INVALID -- stopped: {exc}", file=sys.stderr)
                raise SystemExit(2) from None
        _write_jsonl(out / "run1.jsonl", raw)

    todo = sum(1 for r in raw if r.get("final") and not infra_error(r)
               and (r.get("judge") or {}).get("v") != JUDGE_INPUT_VERSION)
    print(f"scoring: {todo} summaries to judge", flush=True)
    per_case = _score_run(cases, raw, judge)
    _write_jsonl(out / "run1.jsonl", raw)
    rollup = aggregate(per_case, priorities)

    final = final_scores(args.mode, name, cases, raw, rollup, load_baseline())
    (out / "final_scores.json").write_text(json.dumps(final, indent=1) + "\n", encoding="utf-8")
    meta = {"evalset": EVALSET.name, "cases": len(cases), "judge": JUDGE_MODEL,
            "infra_errors": [final["connection_errors"]]}
    (out / "scores.json").write_text(json.dumps(
        {"meta": meta, "runs": [rollup], "cases": [per_case]}, indent=1, default=str) + "\n", encoding="utf-8")
    card = scorecard(name, [rollup], [per_case], meta)
    if final["comparison"]:
        card = card.replace("## Must-capture fields", "\n".join(final["comparison"]) + "\n\n## Must-capture fields", 1)
    left_out = "; ".join(f"{m} ({why})" for m, why in final["excluded_from_verdict"].items())
    header = f"# Verdict: {final['verdict']}\n\n" + (f"**Not in the verdict:** {left_out}\n\n" if left_out else "")
    card = card.replace("# Eval scorecard", header + "# Eval scorecard", 1)
    if final["problems"]:
        card = card.replace("# Eval scorecard", "Not judged: " + "; ".join(final["problems"]) + "\n\n# Eval scorecard", 1)
    (out / "scorecard.md").write_text(card, encoding="utf-8")

    print(card.split("## Failures")[0])
    print(f"VERDICT: {final['verdict']}" + (f" ({', '.join(final['regressed'])})" if final["regressed"] else "")
          + (f" -- {'; '.join(final['problems'])}" if final["problems"] else ""))
    if left_out:
        print(f"not in the verdict: {left_out}")
    print(f"written: {out / 'final_scores.json'}")
    raise SystemExit({"PASS": 0, "REGRESSION": 1, "INVALID": 2}[final["verdict"]])


APP_START_TIMEOUT_S = 180


def _healthy(base_url: str) -> bool:
    import httpx
    try:
        return httpx.get(f"{base_url.rstrip('/')}/healthz", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


@contextlib.contextmanager
def app_running(base_url: str, start: bool):
    """With ``start``, run the app (uvicorn, same Python) for the duration and
    stop it afterwards, waiting until /healthz answers before driving cases.
    Otherwise use the app that is already running."""
    proc = None
    if start:
        port = urllib.parse.urlsplit(base_url).port or 8000
        root = Path(__file__).resolve().parents[2]
        RUNS.mkdir(parents=True, exist_ok=True)
        log = (RUNS / "app.log").open("w", encoding="utf-8")
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                                cwd=root, stdout=log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + APP_START_TIMEOUT_S
        while not _healthy(base_url):
            if proc.poll() is not None or time.monotonic() > deadline:
                proc.kill()
                raise SystemExit(f"The app did not start. See {RUNS / 'app.log'}")
            time.sleep(2)
        print(f"app started (pid {proc.pid}); log: {RUNS / 'app.log'}")
    try:
        yield
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()


def read_run(path: Path) -> list[dict]:
    """The cases in a run1.jsonl. A line that can't be read -- the last one,
    cut off by a Ctrl-C mid-write -- is skipped with a warning; that case then
    counts as never ran, so the run is reported INVALID instead of crashing."""
    rows, bad = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    if bad:
        print(f"warning: skipped {bad} unreadable line(s) in {path.name} (run stopped mid-write?)")
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


if __name__ == "__main__":
    main()
