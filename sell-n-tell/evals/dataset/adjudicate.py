"""Settle the drafted labels with models instead of a line-by-line human review.

    # 1. A blind second labelling: a different model, the same rules, and it
    #    never sees the first model's answers.
    uv run python -m evals.dataset.draft_labels --name pilot --model gemini-2.5-flash --tag second

    # 2. Compare the two. Where they agree, the answer stands. Where they
    #    disagree, a judge reads the note and both answers and settles it. The
    #    result pre-fills the review sheet.
    uv run --with openpyxl python -m evals.dataset.adjudicate --name pilot --force

    # 3. Import exactly as after a human review.
    uv run --with openpyxl python -m evals.dataset.review import --name pilot

Why blind, and why a judge only on disagreements: a model asked "is this answer
right?" while looking at the answer mostly says yes. Two independent answers
that agree are much stronger evidence than one answer that was approved.

What this does NOT give you is a human check. The reviewer recorded on every
record is "LLM check (...)", not a person. Rows the judge settled are coloured
in the sheet; a person can look at just those and override any decision before
importing.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from collections import Counter
from pathlib import Path

from evals.dataset.answers import (
    NOT_DISCUSSED,
    NOT_STATED,
    latest_drafts,
    row_answers,
)
from evals.dataset.draft_labels import (
    DEFAULT_MODEL,
    EVENT_TYPES,
    MAX_ATTEMPTS,
    _client,
    _generate,
    context_text,
    load_dispositions,
    rules_text,
)
from evals.dataset.fields import Catalog, load_catalog
from evals.dataset.paths import OUT

SENTINELS = {NOT_STATED, NOT_DISCUSSED}


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9$%./]+", " ", text.lower()).split())


def agree(a: str, b: str) -> bool:
    """Do two answers to the same question say the same thing?

    "Not stated" only agrees with "not stated". Two values agree when they are
    the same after normalising, or one contains the other ("12 units" and
    "12 units a month").
    """
    if a == b:
        return True
    if a in SENTINELS or b in SENTINELS:
        return False
    na, nb = _norm(a), _norm(b)
    min_len = 3
    return na == nb or (min(len(na), len(nb)) >= min_len and (na in nb or nb in na))


def question_for(key: str, record: dict, catalog: Catalog) -> str:
    if key == "event_type":
        return "Event type"
    fields = {f.field_id: f for f in catalog.fields_for(record["vertical"])}
    if key in fields:
        f = fields[key]
        return f"{f.field_id} {f.name}: {f.captures}"
    return f'Disposition for planned topic "{key}"'


def presentation_order(record_id: str, key: str, a: str, b: str) -> tuple[str, str]:
    """The two answers in a random order that is fixed per item.

    Models lean towards whichever option they read first, and the judge may be
    the same model that wrote answer A -- so A must not always come first. The
    seed makes a re-run show the judge exactly the same prompt.
    """
    rng = random.Random(f"{record_id}|{key}")
    return (a, b) if rng.random() < 0.5 else (b, a)  # noqa: PLR2004


def build_judge_prompt(
    record: dict, catalog: Catalog, dispositions: list[dict], disputed: list[tuple[str, str, str]]
) -> str:
    items = []
    for key, a, b in disputed:
        first, second = presentation_order(record["id"], key, a, b)
        items.append(
            f'- key: "{key}"\n  question: {question_for(key, record, catalog)}\n'
            f"  answer 1: {first}\n  answer 2: {second}"
        )
    items = "\n".join(items)
    return f"""Two annotators labelled the same sales-visit dictation independently and
disagree on the items below. Decide the correct answer for each, using ONLY what
the dictation states. You may pick either answer or give a different one.

{context_text(record, catalog)}

{rules_text(dispositions)}

Disputed items:
{items}

Answer formats:
- Event type: one of {list(EVENT_TYPES)}, or "{NOT_STATED}" if the dictation gives no clue.
- Topic disposition: "{NOT_DISCUSSED}", or the integer code alone (e.g. "8").
- Field: the short value, or "{NOT_STATED}" if the dictation does not state it.

Return exactly this JSON object, one entry per disputed key:
{{"rows": [{{"key": "<key>", "answer": "<answer>", "reason": "<one short sentence>"}}]}}
"""


def normalise_judgement(
    key: str, answer: object, labels: dict[int, str], topic_keys: set[str]
) -> str | None:
    """The judge's answer as a review-sheet value, or None if it is not valid."""
    if not isinstance(answer, str) or not answer.strip():
        return None
    answer = answer.strip()
    if key == "event_type":
        if answer.lower() in {NOT_STATED, "not stated", "null", "none"}:
            return NOT_STATED
        return answer if answer in EVENT_TYPES else None
    if key in topic_keys:
        if answer.lower() == NOT_DISCUSSED:
            return NOT_DISCUSSED
        m = re.match(r"\s*(\d+)", answer)
        code = int(m.group(1)) if m else None
        return f"{code} - {labels[code]}" if code in labels else None
    return NOT_STATED if answer.lower() in {NOT_STATED, "not stated", "null", "none"} else answer


def judge(  # noqa: PLR0917
    client, model: str, record: dict, catalog: Catalog, dispositions: list[dict],
    disputed: list[tuple[str, str, str]], labels: dict[int, str],
) -> dict[str, tuple[str, str]]:
    """key -> (final answer, reason). Raises if the judge never answers validly."""
    topic_keys = {t["title"] for t in record["topics"]}
    prompt = build_judge_prompt(record, catalog, dispositions, disputed)
    last = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            rows = json.loads(_generate(client, model, prompt))["rows"]
        except Exception as exc:  # bad JSON or API error: retry
            last = f"{type(exc).__name__}: {exc}"
            time.sleep(2 * attempt)
            continue
        out = {}
        for row in rows:
            key = row.get("key")
            value = normalise_judgement(key, row.get("answer"), labels, topic_keys)
            if value is not None:
                out[key] = (value, str(row.get("reason", "")).strip())
        missing = [k for k, _, _ in disputed if k not in out]
        if not missing:
            return out
        last = f"no valid answer for {missing}"
    raise RuntimeError(f"{record['id']}: judge failed -- {last}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Settle drafted labels with a second model and a judge.")
    ap.add_argument("--name", default="pilot")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--second-tag", default="second", help="tag used for the blind second labelling")
    ap.add_argument("--judge-model", default=DEFAULT_MODEL)
    ap.add_argument("--location")
    ap.add_argument("--force", action="store_true", help="overwrite an existing review sheet")
    args = ap.parse_args()

    first = {d["id"]: d for d in latest_drafts(args.out / f"drafts_{args.name}.jsonl")}
    second = {d["id"]: d for d in latest_drafts(args.out / f"drafts_{args.name}_{args.second_tag}.jsonl")}
    missing = [i for i, d in first.items() if d.get("draft") is None or (second.get(i) or {}).get("draft") is None]
    if missing:
        raise SystemExit(f"Both labellings must succeed first; missing or failed for {missing}.")

    catalog = load_catalog()
    dispositions = load_dispositions()
    labels = {int(d["code"]): d["label"] for d in dispositions}
    client = _client(args.location)

    prefill: dict[tuple[str, str], tuple[str, str, str, bool]] = {}
    tally: Counter = Counter()
    for n, (rid, rec) in enumerate(first.items(), 1):
        a, b = row_answers(rec["draft"], labels), row_answers(second[rid]["draft"], labels)
        disputed = [(k, a[k], b.get(k, NOT_STATED)) for k in a if not agree(a[k], b.get(k, NOT_STATED))]
        verdicts = judge(client, args.judge_model, rec, catalog, dispositions, disputed, labels) if disputed else {}
        for key, value in a.items():
            kind = "event_type" if key == "event_type" else "topic" if key in {t["title"] for t in rec["topics"]} else "field"
            if key not in verdicts:
                prefill[(rid, key)] = ("Accept", "", "A and B agree", False)
                tally[(kind, "agreed")] += 1
                continue
            final, reason = verdicts[key]
            side = "A" if agree(final, value) else "B" if agree(final, b.get(key, NOT_STATED)) else "neither"
            tally[(kind, f"judge chose {side}")] += 1
            decision = "Accept" if side == "A" else "Correct"
            prefill[(rid, key)] = (decision, "" if decision == "Accept" else final,
                                   f"judge ({side}): {reason} | B said: {b.get(key, NOT_STATED)}", True)
        print(f"  [{n}/{len(first)}] {rid}: {len(disputed)} disputed")

    model_a = next(iter(first.values())).get("model")
    model_b = next(iter(second.values())).get("model")
    reviewer = f"LLM check: A={model_a}, B={model_b} (blind), judge={args.judge_model}"
    # Imported here: review.py needs openpyxl, and the unit tests import this
    # module without it.
    from evals.dataset.review import export  # noqa: PLC0415

    export(args.name, args.out, args.force, prefill, reviewer)

    total = sum(tally.values())
    agreed = sum(n for (_, what), n in tally.items() if what == "agreed")
    lines = [f"# Adjudication '{args.name}' -- summary (counts only)", "",
             f"{reviewer}", "",
             f"rows: {total}   agreed: {agreed} ({agreed / max(total, 1):.0%})   "
             f"settled by judge: {total - agreed}", ""]
    for kind in ("event_type", "topic", "field"):
        parts = [f"{what} {n}" for (k, what), n in sorted(tally.items()) if k == kind]
        lines.append(f"    {kind:<11} " + ", ".join(parts))
    lines += ["", "Judged rows are coloured blue in the review sheet; check those by hand "
              "if a person should sign off."]
    (args.out / f"adjudicate_{args.name}_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
