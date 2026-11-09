"""Score extract() (AIML-2929) on the eval sets -- no live conversation.

    uv run python -m evals.extract_eval.run --model <model>                      # golden, 3 runs
    uv run python -m evals.extract_eval.run --model <model> --set golden topup synthetic
    uv run python -m evals.extract_eval.run --model <model> --repeats 1 --limit 10   # a first look

Planned topics get their short description from the campaign registry
(evals/reference/campaign_topics.csv, fetched from the eval bucket; see
evals/README.md), looked up by the account's vertical.

Each note goes straight to extract(); the record is scored with the harness's
own scorer (evals/agent_eval/score.py) and the summaries with the same judge,
so the numbers compare with the agent's baseline. By default the record has
no disposition codes, so disposition is n/a and left out of the comparison.
With ``--dispositions`` (AIML-3004) each discussed topic gets a code from the
agent's registry, and disposition is scored and compared like the agent's.

A topic extract() marks ``unconfirmed`` (no quote of the rep's words) counts
as not discussed here: in the live flow the rep would be asked, so the count
of unconfirmed topics is reported as the questions that would add.

Writes evals/runs/extract-<time>/ (git-ignored): per set a scorecard, the
scores and every raw record, plus summary.json (numbers only).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.extraction import (  # noqa: E402
    DISCUSSED, extract, fields_for, load_catalog, load_dispositions, load_registry)
from app.extraction.catalog import VERTICALS  # noqa: E402
from evals.agent_eval.baseline import compare as compare_to_baseline  # noqa: E402
from evals.agent_eval.baseline import load as load_baseline  # noqa: E402
from evals.agent_eval.baseline import summarise  # noqa: E402
from evals.agent_eval.cases import EVALSET, GOLDEN_DIR, dataset_sha256, load_cases, load_priorities  # noqa: E402
from evals.agent_eval.judge import DEFAULT_MODEL as JUDGE_MODEL  # noqa: E402
from evals.agent_eval.run import scorecard  # noqa: E402
from evals.agent_eval.score import aggregate, score_case, variance  # noqa: E402

RUNS = ROOT / "evals" / "runs"
# The top-up and synthetic sets sit next to the golden folder (fetched from
# the eval bucket like it -- see evals/README.md).
SETS_DIR = Path(os.environ.get("SELLNTELL_EVAL_SETS") or GOLDEN_DIR.parent)
REGISTRY = SETS_DIR / "reference" / "campaign_topics.csv"
LABELLING_MODELS = ("gemini-3.8-flash", "gemini-3.1-pro-preview")  # built the golden set's answers
WORKERS = 8


def set_files(name: str) -> list[Path]:
    if name == "golden":
        return [EVALSET]
    pattern = {"topup": "golden_topup_v*.evalset.json", "synthetic": "golden_synthetic_v*.evalset.json"}[name]
    files = sorted((SETS_DIR / name).glob(pattern))
    if not files:
        raise SystemExit(f"No {name} set found in {SETS_DIR / name} (see evals/README.md).")
    return files


def set_cases(name: str, limit: int | None = None) -> list:
    """The set's cases from every file in its folder: the top-up comes in
    rounds of different notes (golden_topup_v1..v3), not versions of one key.
    An id in two files, or a vertical with no field list, is a data mistake,
    so the run stops before any call rather than drop, double-count or crash
    on a case part-way through."""
    cases, seen = [], {}
    for f in set_files(name):
        for c in load_cases(f, strict=(name == "golden")):
            if c.id in seen:
                raise SystemExit(f"{name}: case {c.id} is in both {seen[c.id]} and {f.name}; "
                                 "ids must be unique across the set's files")
            if c.vertical not in VERTICALS:
                raise SystemExit(f"{name}: case {c.id} has vertical {c.vertical!r} in {f.name}; "
                                 f"expected one of {', '.join(VERTICALS)}")
            seen[c.id] = f.name
            cases.append(c)
    return cases[:limit]


def key_sha256(name: str) -> str:
    """The checksum of the answer key this set was scored on."""
    sums = [dataset_sha256(f) for f in set_files(name)]
    return sums[0] if len(sums) == 1 else hashlib.sha256("\n".join(sums).encode()).hexdigest()


def reply_error(row: dict) -> bool:
    """The model answered, but not with a record (see ExtractResult.error_kind).
    Rows saved before error_kind existed are told by the error's text."""
    kind = row.get("error_kind")
    return kind == "reply" or (kind is None and str(row.get("error") or "").startswith("reply does not fit"))


def score_row(case, record: dict | None, codes: bool = False) -> dict:
    """``record`` None: the model's reply was not a record -- scored like an
    agent that never staged, every topic and stated field a miss. ``codes``:
    the run asked for disposition codes, so they are scored."""
    s = score_case(case, to_scorer_args(record))
    if not codes:
        for t in s["topics"]:      # no codes in the record: disposition is n/a, not 0
            t.pop("code_ok", None)
    return s


def to_scorer_args(record: dict | None) -> dict | None:
    """extract()'s record in the shape the scorer reads (the stage_visit_notes
    arguments). Only a confirmed ``discussed`` topic counts as discussed."""
    if record is None:
        return None
    return {"event_type": record["event_type"], "executive_summary": record["executive_summary"],
            "topics": [{"topic": t["topic"], "discussed": t["status"] == DISCUSSED,
                        "executive_summary": t["summary"],
                        **({"disposition_code": t["disposition_code"]} if "disposition_code" in t else {})}
                       for t in record["topics"]],
            "must_capture": dict(record["must_capture"])}


def _client(location: str):
    from dotenv import load_dotenv
    from google import genai
    from google.genai import types
    load_dotenv(ROOT / "app" / ".env")
    return genai.Client(vertexai=True, location=location, project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                        http_options=types.HttpOptions(timeout=120_000))


def run_once(cases, catalog, client, model: str, registry, judge, thinking=None,
             dispositions: dict[int, str] | None = None) -> list[dict]:
    """One pass over the cases: extract, score, judge. Returns per-case rows."""
    codes = bool(dispositions)

    def one(case):
        descriptions = registry.descriptions(case.planned_topics, case.vertical) if registry else {}
        res = extract(case.note, case.planned_topics, case.vertical, fields_for(catalog, case.vertical),
                      client=client, model=model, descriptions=descriptions, thinking=thinking,
                      dispositions=dispositions)
        args = to_scorer_args(res.record)
        s = None       # a failed call says nothing about the model: not scored, only counted
        if args is not None:
            s = score_row(case, res.record, codes)
            verdict = judge.check(case.note, args) if judge else {}
            s["faithful"], s["unsupported"] = verdict.get("faithful"), verdict.get("unsupported")
        elif res.error_kind == "reply":    # the model's own failure: scored as a miss
            s = score_row(case, None, codes)
        return {"id": case.id, "score": s, "record": res.record, "error": res.error,
                "error_kind": res.error_kind, "codes_downgraded": res.codes_downgraded,
                # the model's words for each failed check (not in the record)
                "rejected": res.rejected,
                "unconfirmed": res.unconfirmed, "off_plan_labels": res.off_plan,
                "described": sorted(descriptions), "usage": res.usage}
    with ThreadPoolExecutor(WORKERS) as pool:
        return list(pool.map(one, cases))


PRICES = Path(__file__).with_name("prices.json")
# Same rule as the agent harness: above this share of failed calls a run is
# INVALID -- failures are not model behaviour, so it is not compared.
MAX_ERROR_RATE = 0.10
# Same limit as the agent harness: above this share of summaries the judge
# could not judge, faithfulness is shown but not compared.
MAX_UNJUDGED_RATE = 0.10


def _mean_pct(values: list) -> float | None:
    """Mean over the repeats, in percent; None when no repeat had any."""
    vals = [v * 100 for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def usage_summary(rows: list[dict], model: str, prices: dict) -> dict:
    """Tokens, time and (when the model's price is set in prices.json) cost of
    the extraction calls in one run. Thinking tokens are billed as output.
    Per-note figures and latency are over the calls the model answered: a
    failed call has no tokens, and its time is the timeout, not the model's."""
    use = [u for u in (r.get("usage") or {} for r in rows) if "input_tokens" in u]
    tok_in = sum(u.get("input_tokens", 0) for u in use)
    tok_out = sum(u.get("output_tokens", 0) + u.get("thinking_tokens", 0) for u in use)
    secs = sorted(u["seconds"] for u in use if "seconds" in u)
    n = len(use) or 1
    # cost_usd covers the calls the model answered (a failed call has no tokens)
    out = {"calls": len(rows), "answered_calls": len(use), "input_tokens": tok_in, "output_tokens": tok_out,
           "input_tokens_per_note": round(tok_in / n), "output_tokens_per_note": round(tok_out / n),
           "seconds_p50": secs[len(secs) // 2] if secs else None,
           "seconds_p95": secs[min(len(secs) - 1, int(len(secs) * 0.95))] if secs else None}
    price = prices.get(model) or {}
    if price.get("input_per_million") is not None and price.get("output_per_million") is not None:
        cost = tok_in / 1e6 * price["input_per_million"] + tok_out / 1e6 * price["output_per_million"]
        out.update(cost_usd=round(cost, 4), cost_per_1000_notes_usd=round(cost / n * 1000, 2),
                   price_from=price.get("from"))
        later = price.get("from_2027") or {}
        if later.get("input_per_million") is not None:
            cost_later = tok_in / 1e6 * later["input_per_million"] + tok_out / 1e6 * later["output_per_million"]
            out["cost_per_1000_notes_usd_from_2027"] = round(cost_later / n * 1000, 2)
    else:
        out["cost_usd"] = None
    return out


def rescore_rows(cases, rows: list[dict], codes: bool = False) -> list[dict]:
    """Score saved records again against the current answer key (e.g. after a
    key correction). The judge's verdicts are kept: the summaries did not
    change. No model call. ``codes``: the run asked for disposition codes."""
    by_id = {c.id: c for c in cases}
    out = []
    for row in rows:
        case = by_id.get(row["id"])
        if case is None:
            continue
        if row.get("error") or row.get("record") is None:
            # a failed call has nothing to score; a reply that was not a record is a miss
            out.append(dict(row, score=score_row(case, None, codes) if reply_error(row) else None))
            continue
        s = score_row(case, row["record"], codes)
        old = row.get("score") or {}
        s["faithful"], s["unsupported"] = old.get("faithful"), old.get("unsupported")
        out.append(dict(row, score=s))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Score extract() on the eval sets (no live conversation).")
    ap.add_argument("--model", help="the Gemini model extract() uses (required unless --rescore)")
    ap.add_argument("--rescore", type=Path, metavar="RUN_DIR",
                    help="re-score a saved extract run against the current answer key; no model calls")
    ap.add_argument("--location", default="global")
    ap.add_argument("--set", nargs="+", default=["golden"], choices=("golden", "topup", "synthetic"))
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--registry", type=Path, default=REGISTRY, help="the Campaign Topics export")
    ap.add_argument("--no-descriptions", action="store_true", help="titles only (to measure what descriptions add)")
    ap.add_argument("--limit", type=int, help="only the first N cases of each set (a first look; not comparable)")
    ap.add_argument("--allow-labelling-model", action="store_true",
                    help="run a model that labelled the golden set; its scores are marked as possibly flattering")
    ap.add_argument("--thinking", help="minimal / low / medium / high (3.x models), or a token budget "
                                       "such as 0 for off (2.5 models); default: the model's own")
    ap.add_argument("--dispositions", action="store_true",
                    help="each discussed topic also gets a disposition code from the agent's registry; "
                         "disposition is then scored and compared (AIML-3004)")
    ap.add_argument("--judge-model", default=JUDGE_MODEL,
                    help="the faithfulness judge; should differ from --model (a model judging itself flatters)")
    args = ap.parse_args()
    if args.rescore:
        out = args.rescore
        prior = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        # The run's own settings come back from its summary, so the scorecard
        # header and the judge named on it stay what the run actually used.
        args.model, args.limit = prior["model"], prior.get("limit")
        args.thinking, args.location = prior.get("thinking"), prior.get("location") or args.location
        args.dispositions = bool(prior.get("dispositions"))
        args.set = [s for s in prior["sets"] if (out / f"raw_{s}_r1.jsonl").exists()]
        # Sets that cannot be re-scored (no raw files) keep their previous entry.
        summary = dict(prior, sets=dict(prior["sets"]),
                       rescored_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                       dataset_sha256=dataset_sha256(EVALSET))
        priorities, registry = load_priorities(), None
    else:
        if not args.model:
            raise SystemExit("--model is required (or --rescore RUN_DIR)")
        if args.model in LABELLING_MODELS and not args.allow_labelling_model:
            raise SystemExit(f"{args.model} labelled the golden set, so its scores may flatter it. "
                             "Pass --allow-labelling-model to run it anyway (the scorecard says so).")
        if args.judge_model == args.model:
            print(f"note: {args.model} judges its own summaries; the scorecard says so.", flush=True)
        if not args.no_descriptions and not args.registry.exists():
            raise SystemExit(f"Campaign registry not found: {args.registry} (see evals/README.md), "
                             "or pass --no-descriptions.")
        for name in args.set:       # a missing set or a repeated id stops the run here, before any call
            set_cases(name)
        from evals.agent_eval.judge import Judge
        catalog, priorities = load_catalog(GOLDEN_DIR), load_priorities()
        registry = None if args.no_descriptions else load_registry(args.registry)
        dispositions = load_dispositions() if args.dispositions else None
        client, judge = _client(args.location), Judge(model=args.judge_model)
        out = RUNS / f"extract-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        out.mkdir(parents=True)
        summary = {"model": args.model, "judge_model": args.judge_model, "repeats": args.repeats,
                   "location": args.location, "thinking": args.thinking, "dispositions": args.dispositions,
                   "labelled_the_golden_set": args.model in LABELLING_MODELS,
                   "registry": None if registry is None else args.registry.name,
                   "registry_sha256": None if registry is None else hashlib.sha256(args.registry.read_bytes()).hexdigest(),
                   "limit": args.limit, "dataset_sha256": dataset_sha256(EVALSET),
                   "scored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "sets": {}}

    for name in args.set:
        cases = set_cases(name, args.limit)
        if registry is not None:
            topics = [(t, c.vertical) for c in cases for t in c.planned_topics]
            summary.setdefault("described_topic_mentions", {})[name] = (
                f"{sum(registry.lookup(t, v) is not None for t, v in topics)}/{len(topics)}")
        runs, per_case, errors, unconfirmed, dropped, all_rows = [], [], 0, 0, 0, []
        downgraded = 0
        reply_errors = unjudged = judgeable = 0
        repeats = len(list(out.glob(f"raw_{name}_r*.jsonl"))) if args.rescore else args.repeats
        args.repeats = repeats
        for k in range(1, repeats + 1):
            raw_file = out / f"raw_{name}_r{k}.jsonl"
            if args.rescore:
                print(f"{name}: re-scoring run {k}/{repeats}", flush=True)
                rows = rescore_rows(cases, [json.loads(line) for line in
                                            raw_file.read_text(encoding="utf-8").splitlines() if line.strip()],
                                   args.dispositions)
            else:
                print(f"{name}: run {k}/{repeats}, {len(cases)} cases", flush=True)
                rows = run_once(cases, catalog, client, args.model, registry, judge, args.thinking,
                                dispositions)
            if not args.rescore:
                # Only a fresh run writes the records. A re-score reads them and
                # leaves the file as it is: the records did not change, and
                # rewriting it would drop any row not in the set loaded now.
                raw_file.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                    encoding="utf-8")
            scores = [r["score"] for r in rows if r["score"] is not None]   # failed calls left out
            runs.append(aggregate(scores, priorities))
            per_case.append(scores)
            errors += sum(1 for r in rows if r["error"])
            reply_errors += sum(1 for r in rows if r["error"] and reply_error(r))
            judgeable += sum(1 for r in rows if r.get("record") is not None)
            unjudged += sum(1 for r in rows if r.get("record") is not None
                            and (r["score"] or {}).get("faithful") is None)
            unconfirmed += sum(len(r["unconfirmed"]) for r in rows)
            dropped += sum(len(r["off_plan_labels"]) for r in rows)
            downgraded += sum(len(r.get("codes_downgraded") or []) for r in rows)
            all_rows += rows
        meta = {"evalset": ", ".join(f.name for f in set_files(name)), "cases": len(cases),
                "judge": summary.get("judge_model", JUDGE_MODEL)}
        usage = usage_summary(all_rows, args.model,
                              json.loads(PRICES.read_text(encoding="utf-8")) if PRICES.exists() else {})
        runs = [r for r in runs if r]              # a repeat where every call failed has nothing to roll up
        per_case = [p for p in per_case if p]
        title = f"extract() on {name} -- {args.model}"
        card = (scorecard(title, runs, per_case, meta) if runs else
                f"# Eval scorecard: {title}\n\n## Overall\n\nNo call succeeded.\n\n## Must-capture fields\n")
        skip = [] if args.dispositions else ["disposition"]
        if unjudged > MAX_UNJUDGED_RATE * judgeable:
            skip.append("faithfulness")
        entry = {"cases": len(cases), "key_sha256": key_sha256(name), "schema_or_call_errors": errors,
                 # of those, replies that were not a record: scored as misses, the
                 # rest (failed calls) are left out of the scores
                 "reply_errors": reply_errors,
                 # summaries the judge could not judge: left out of faithfulness
                 "unjudged_summaries": unjudged,
                 # labels the model returned that match no planned topic -- should
                 # be 0 now the schema allows only the planned labels
                 "dropped_topic_labels": dropped,
                 "unconfirmed_topics_per_run": round(unconfirmed / args.repeats, 1),
                 # codes set to 99 because the rep's words for them were not in the note
                 **({"codes_downgraded_per_run": round(downgraded / args.repeats, 1)} if args.dispositions else {}),
                 "usage": usage, "scores": summarise(runs) if runs else {},
                 # recall counts any filled field; this is how many of those match the key
                 "value_accuracy": {p: _mean_pct([(r["all"]["fields"].get(p) or {}).get("value_accuracy")
                                                  for r in runs]) for p in ("P1", "all")},
                 "spread": variance(runs) if runs else {}}
        calls, failed = len(cases) * args.repeats, errors - reply_errors
        if failed > MAX_ERROR_RATE * calls:
            # Failed calls are left out of the scores, so the means would rest on
            # too few cases to say anything about the model: not compared.
            first = next((r["error"] for r in all_rows if r["error"] and not reply_error(r)), "")
            entry["invalid"] = f"{failed} of {calls} calls failed (limit {MAX_ERROR_RATE:.0%}); first: {first[:200]}"
            entry["comparison"] = [f"**INVALID -- not compared.** {entry['invalid']}"]
            print(f"INVALID: {entry['invalid']}", flush=True)
        elif name == "golden" and args.limit:
            entry["comparison"] = [f"not compared: --limit {args.limit} scores a subset"]
        elif name == "golden":
            ref = load_baseline()
            if ref is None:
                entry["comparison"] = ["no committed baseline"]
            elif ref.get("dataset_sha256") != dataset_sha256(EVALSET):
                entry["comparison"] = ["the golden set differs from the baseline's; re-score the baseline first"]
            else:
                entry["comparison"], _ = compare_to_baseline(runs, ref, "full", skip=skip)
        if "comparison" in entry:
            card = card.replace("## Must-capture fields", "\n".join(entry["comparison"]) + "\n\n## Must-capture fields", 1)
        card = card.replace("## Overall", f"Model: `{args.model}`"
                            f"{f' (thinking: {args.thinking})' if getattr(args, 'thinking', None) else ''}. "
                            f"Schema or call errors: {errors} "
                            f"(across {args.repeats} runs; {reply_errors} were replies that were not a "
                            f"record, scored as misses). Summaries not judged: {unjudged} of {judgeable}"
                            f"{' -- faithfulness not compared' if 'faithfulness' in skip else ''}. "
                            f"Dropped topic labels: {dropped}"
                            f"{' -- CHECK: these planned topics scored as not discussed' if dropped else ''}. "
                            f"Unconfirmed topics (questions the live flow "
                            f"would ask): {entry['unconfirmed_topics_per_run']} per run."
                            + (f" Disposition codes set to 99 for want of the rep's words: "
                               f"{entry['codes_downgraded_per_run']} per run." if args.dispositions else "")
                            + "\n\n"
                            f"Cost: {usage['input_tokens_per_note']} input + {usage['output_tokens_per_note']} "
                            f"output tokens per note, {usage['seconds_p50']} s median / {usage['seconds_p95']} s p95 "
                            f"per call; " + (f"${usage['cost_usd']} for {usage['answered_calls']} answered calls, "
                                             f"${usage['cost_per_1000_notes_usd']} per 1,000 notes"
                                             + (f" (${usage['cost_per_1000_notes_usd_from_2027']} from 2027)"
                                                if "cost_per_1000_notes_usd_from_2027" in usage else "")
                                             if usage["cost_usd"] is not None
                                             else f"price for {args.model} not set in evals/extract_eval/prices.json")
                            + ".\n\n"
                            + (f"**Caution: `{args.model}` helped label the golden set; its scores may be "
                               "flattering.**\n\n" if args.model in LABELLING_MODELS else "")
                            + (f"Note: faithfulness was judged by `{args.model}` itself.\n\n"
                               if summary.get("judge_model") == args.model else "")
                            + "## Overall", 1)
        (out / f"scorecard_{name}.md").write_text(card, encoding="utf-8")
        (out / f"scores_{name}.json").write_text(json.dumps({"meta": meta, "runs": runs, "cases": per_case},
                                                            indent=1, default=str) + "\n", encoding="utf-8")
        summary["sets"][name] = entry
        # After every set, so a finished set can be read (compare, --rescore)
        # even if a later one stops the run.
        (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n", encoding="utf-8")
        print(card.split("## Failures")[0])

    print(f"written: {out}")


if __name__ == "__main__":
    main()
