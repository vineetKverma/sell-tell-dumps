"""Every disposition miss in a saved extract_eval run, sorted into kinds --
read-only, no model calls.

    cd <repo>; uv run python C:\\tmp\\disposition_misses.py evals\\runs\\extract-<id> [--notes] [--only=ID,ID]

Kinds of miss (expected code from the answer key, actual from the record):
  not discussed     the key says discussed; the record says not discussed
  unconfirmed       the record says discussed but its evidence failed the check
  model 99          a real code expected; the model itself answered 99
  fallback 99       a real code expected; the model gave a code, our check set 99
  wrong real code   a real code expected; a different real code given
  real for 99       the key says 99; the model gave a real code
"""

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.getcwd())

from app.extraction import load_dispositions  # noqa: E402
from evals.extract_eval.run import set_cases  # noqa: E402

NONE_FITS = 99


def kind(exp: int, rec_topic: dict | None, downgraded: bool) -> str:
    status = (rec_topic or {}).get("status")
    if status == "unconfirmed":
        return "unconfirmed"
    if status != "discussed":
        return "not discussed"
    got = rec_topic.get("disposition_code")
    if got == NONE_FITS:
        return "fallback 99" if downgraded else "model 99"
    return "real for 99" if exp == NONE_FITS else "wrong real code"


def main() -> None:
    run = Path(sys.argv[1])
    show_notes = "--notes" in sys.argv
    only = next((a.split("=", 1)[1].split(",") for a in sys.argv if a.startswith("--only=")), None)
    labels = {c: l.split(" (e.g.")[0] for c, l in load_dispositions().items()}
    cases = {c.id: c for c in set_cases("golden", None)}
    kinds, scored, right = Counter(), 0, 0
    by_topic = defaultdict(list)          # (case, topic) -> [(run, kind, actual, outcome words)]
    expected_mix = Counter()
    over, not_discussed = defaultdict(list), 0   # (case, topic) -> marked discussed, the key says not
    for raw in sorted(run.glob("raw_golden_r*.jsonl")):
        k = raw.stem.rsplit("_r", 1)[1]
        for line in raw.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            s, rec = row.get("score"), row.get("record")
            if not s:
                continue
            rec_topics = {t["topic"]: t for t in (rec or {}).get("topics", [])}
            for t in s["topics"]:
                if "code_ok" not in t:      # the key says not discussed
                    rt = rec_topics.get(t["topic"]) or {}
                    not_discussed += 1
                    if rt.get("status") == "discussed":
                        over[(row["id"], t["topic"])].append(
                            (k, rt.get("disposition_code"), rt.get("evidence", ""), rt.get("summary", "")))
                    continue
                scored += 1
                exp = t["expected_code"]
                expected_mix["99" if exp == NONE_FITS else "real"] += 1
                if t["code_ok"]:
                    right += 1
                    continue
                rt = rec_topics.get(t["topic"])
                what = kind(exp, rt, t["topic"] in (row.get("codes_downgraded") or []))
                kinds[what] += 1
                failed = (row.get("rejected") or {}).get(t["topic"])   # words in older runs, sentence numbers from AIML-3152 on
                by_topic[(row["id"], t["topic"])].append(
                    (k, what, (rt or {}).get("disposition_code"), (rt or {}).get("outcome_evidence", ""),
                     (rt or {}).get("summary", ""), failed))

    print(f"Run {run.name}: {right}/{scored} codes right = {100 * right / max(scored, 1):.1f}%  "
          f"(expected 99: {expected_mix['99']}, expected a real code: {expected_mix['real']})\n")
    print("Misses by kind:")
    for name, n in kinds.most_common():
        print(f"  {name:16s} {n}")
    repeats = len(list(run.glob("raw_golden_r*.jsonl")))
    print(f"\nMissed topics ({len(by_topic)}), most often missed first:")
    for (cid, topic), misses in sorted(by_topic.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if only and cid not in only:
            continue
        case = cases[cid]
        exp = next(t["disposition_code"] for t in case.topics if t["topic"] == topic)
        print(f"\n- {cid} | {topic} | missed {len(misses)}/{repeats} | expected {exp} {labels.get(exp, '')}")
        for k, what, got, words, summary, failed in misses:
            print(f"    r{k}: {what}; got {got} {labels.get(got, '') if got is not None else ''}"
                  + (f"; words: \"{words}\"" if words else "")
                  + (f"; summary: \"{summary[:160]}\"" if summary else ""))
            if failed:
                print(f"        model gave (failed the check): {failed}")
        if show_notes:
            print(f"    note: {case.note}")

    marked = sum(len(v) for v in over.values())
    print(f"\nOver-claimed: {marked}/{not_discussed} topics the key says were not discussed "
          f"= {100 * marked / max(not_discussed, 1):.1f}%  ({len(over)} topics)")
    for (cid, topic), hits in sorted(over.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        print(f"\n- {cid} | {topic} | marked discussed {len(hits)}/{repeats}")
        for k, code, evidence, summary in hits:
            print(f"    r{k}: code {code}; evidence: \"{evidence[:200]}\"; summary: \"{summary[:160]}\"")
        if show_notes:
            print(f"    note: {cases[cid].note}")


if __name__ == "__main__":
    main()
