"""Compare two finished answer keys built from the same notes (AIML-2898).

    uv run python -m evals.dataset.compare_keys --a pilot --b pilot_g

Answers the question "does a different set of models change the answers?".
Where the two keys agree, the label is stable whichever models made it. Where
they differ, the item is genuinely hard -- the place a human look pays off.

Uses the same notion of "the same answer" as the adjudicator (``agree``), so a
wording difference ("12 units" vs "12 units a month") is not a disagreement.

Writes ``compare_<a>_vs_<b>.md``: counts, and WHICH items differ (record id +
field), never the values themselves -- values can carry names from the notes.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evals.dataset.adjudicate import agree
from evals.dataset.answers import NOT_DISCUSSED, NOT_STATED
from evals.dataset.draft_labels import DERIVED_FIELDS
from evals.dataset.fields import load_catalog
from evals.dataset.paths import OUT


def load_key(path: Path) -> dict[str, dict]:
    return {
        rec["id"]: rec
        for rec in (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
    }


def flatten(expected: dict) -> dict[str, tuple[str, str]]:
    """key -> (kind, comparable answer)."""
    out = {"event_type": ("event_type", expected.get("event_type") or NOT_STATED)}
    for t in expected.get("topics", []):
        answer = str(t["disposition_code"]) if t.get("discussed") else NOT_DISCUSSED
        out[t["title"]] = ("topic", answer)
    for fid, value in expected.get("fields", {}).items():
        if fid in DERIVED_FIELDS:  # restates the topic answers; would double-count
            continue
        out[fid] = ("field", NOT_STATED if value in (None, "") else str(value))
    return out


def compare(key_a: dict[str, dict], key_b: dict[str, dict], priority: dict[str, int]):
    tally: Counter = Counter()
    differing: list[tuple[str, str, str]] = []  # (record, key, how)
    for rid in sorted(set(key_a) & set(key_b)):
        a, b = flatten(key_a[rid]["expected"]), flatten(key_b[rid]["expected"])
        vertical = key_a[rid]["vertical"]
        for k, (kind, va) in a.items():
            vb = b.get(k, (kind, NOT_STATED))[1]
            group = f"field P{priority.get(k, '?')}" if kind == "field" else kind
            same = agree(va, vb)
            for bucket in (group, vertical, "all"):
                tally[(bucket, same)] += 1
            if not same:
                how = ("stated only in A" if vb == NOT_STATED else
                       "stated only in B" if va == NOT_STATED else "different value")
                differing.append((rid, k, how))
    return tally, differing


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare two answer keys built from the same notes.")
    ap.add_argument("--a", required=True, help="run name of the first key, e.g. pilot")
    ap.add_argument("--b", required=True, help="run name of the second key, e.g. pilot_g")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    key_a = load_key(args.out / f"reviewed_{args.a}.jsonl")
    key_b = load_key(args.out / f"reviewed_{args.b}.jsonl")
    shared = set(key_a) & set(key_b)
    if not shared:
        raise SystemExit("The two keys share no records -- were they built from the same sample?")

    catalog = load_catalog()
    priority = {f.field_id: f.priority for f in catalog.all_fields}
    tally, differing = compare(key_a, key_b, priority)

    def line(bucket: str) -> str:
        same, diff = tally[(bucket, True)], tally[(bucket, False)]
        return f"    {bucket:<12} {same:>4} / {same + diff:<4} ({same / max(same + diff, 1):.0%} agree)"

    def reviewer(key: dict[str, dict]) -> str:
        return next(iter(key.values())).get("reviewed_by", "?")

    lines = [
        f"# Answer key '{args.a}' vs '{args.b}' (counts only)", "",
        f"A: {reviewer(key_a)}", f"B: {reviewer(key_b)}", "",
        f"records compared: {len(shared)}"
        + (f"   (only in one key: {len(set(key_a) ^ set(key_b))})" if set(key_a) ^ set(key_b) else ""),
        "", "## Same answer in both keys", "",
        line("all"), "",
    ]
    groups = sorted({b for b, _ in tally if b.startswith(("event", "topic", "field"))})
    verticals = sorted({b for b, _ in tally} - set(groups) - {"all"})
    lines += [line(g) for g in groups] + [""] + [line(v) for v in verticals]
    lines += ["", "## How they differ", ""]
    lines += [f"    {n:>4}  {how}" for how, n in Counter(h for _, _, h in differing).most_common()] or ["    none"]
    lines += ["", "## Which items differ (look at these by hand)", ""]
    lines += [f"    {rid}  {k}  ({how})" for rid, k, how in differing] or ["    none"]

    path = args.out / f"compare_{args.a}_vs_{args.b}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nWritten to {path}")


if __name__ == "__main__":
    main()
