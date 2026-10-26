"""One table from several extract_eval runs, read from their summary.json --
so a report is checked against the runs' own numbers, not retyped.

    uv run python -m evals.extract_eval.compare evals/runs/extract-A evals/runs/extract-B ...

Per run (the golden set unless --set): model, thinking, location, the key it
was scored on (dataset sha256, first 8), what decides whether two runs compare
(--limit, campaign descriptions, a labelling model, the judge, summaries not
judged), means over the repeats, value accuracy, errors, dropped labels, cost
and latency.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

COLUMNS = ("event_type", "topic_status", "over_claimed", "disposition", "faithfulness",
           "field_recall_P1", "field_recall_all", "field_invented_rate")


def row(run: Path, set_name: str) -> dict:
    s = json.loads((run / "summary.json").read_text(encoding="utf-8"))
    entry = (s.get("sets") or {}).get(set_name)
    if entry is None:
        return {"run": run.name, "missing": f"no {set_name} set"}
    scores, use = entry.get("scores") or {}, entry.get("usage") or {}
    return {"run": run.name, "model": s.get("model"), "thinking": s.get("thinking") or "default",
            # the set's own key; runs saved before that was recorded have only the golden one
            "location": s.get("location") or "global",
            "key": (entry.get("key_sha256") or (s.get("dataset_sha256") if set_name == "golden" else "") or "")[:8],
            "repeats": s.get("repeats"), "invalid": entry.get("invalid"),
            "limit": s.get("limit"), "descriptions": "yes" if s.get("registry") else "titles only",
            "labelling_model": "yes" if s.get("labelled_the_golden_set") else "no",
            "judge": s.get("judge_model"), "unjudged": entry.get("unjudged_summaries"),
            **{c: (scores.get(c) or {}).get("mean") for c in COLUMNS},
            "value_acc_P1": (entry.get("value_accuracy") or {}).get("P1"),
            "value_acc_all": (entry.get("value_accuracy") or {}).get("all"),
            "errors": entry.get("schema_or_call_errors"), "dropped": entry.get("dropped_topic_labels"),
            "unconfirmed": entry.get("unconfirmed_topics_per_run"),
            # codes set to 99 for want of the rep's words (runs with --dispositions)
            "codes_to_99": entry.get("codes_downgraded_per_run"),
            "usd_per_1k": use.get("cost_per_1000_notes_usd"), "usd_per_1k_2027": use.get("cost_per_1000_notes_usd_from_2027"),
            "p50_s": use.get("seconds_p50"), "p95_s": use.get("seconds_p95"),
            "in_tok": use.get("input_tokens_per_note"), "out_tok": use.get("output_tokens_per_note")}


def table(rows: list[dict]) -> str:
    head = ["run", "model", "thinking", "location", "key", "repeats", "limit", "descriptions",
            "labelling_model", "judge", "unjudged", *COLUMNS, "value_acc_P1", "value_acc_all", "errors", "dropped",
            "unconfirmed", "codes_to_99", "usd_per_1k", "usd_per_1k_2027", "p50_s", "p95_s", "in_tok", "out_tok", "invalid"]
    def fmt(h, v):
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:.2f}" if h.startswith("usd") or h.endswith("_s") else f"{v:.1f}"
        return " ".join(str(v).split()).replace("|", "/")     # an error message must not break the table
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        lines.append("| " + " | ".join(fmt(h, r.get(h)) if "missing" not in r else (r["run"] if h == "run" else
                                       r["missing"] if h == "model" else "") for h in head) + " |")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare extract_eval runs from their summary.json.")
    ap.add_argument("runs", type=Path, nargs="+")
    ap.add_argument("--set", default="golden", choices=("golden", "topup", "synthetic"))
    args = ap.parse_args()
    print(table([row(r, args.set) for r in args.runs]))


if __name__ == "__main__":
    main()
