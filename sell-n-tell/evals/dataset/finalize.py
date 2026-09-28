"""Merge two answer keys, check the result, and freeze it (AIML-2898, last step).

    uv run python -m evals.dataset.finalize --a full_a --b full_b --version v1

The two keys were built independently from the same notes, with the models'
roles swapped. For every answer:

- both keys agree  -> that is the answer
- they disagree    -> the item is CONTESTED: kept in the record, listed under
                      ``expected.contested``, and skipped when the agent is
                      scored. A person may settle it later; nothing guesses.

The merged key is then checked (every record complete, every value allowed,
personal data masked, strata covered). Only if every check passes is it
frozen as ``golden_<version>.jsonl`` with a manifest holding its SHA-256, so
the eval always runs against exactly this file. A frozen version is never
overwritten -- make a new version instead.

Writes (evals/data/out/):
  golden_<version>.jsonl           the frozen answer key (contains notes; stays here)
  golden_<version>.manifest.json   checksum, counts, which runs and models built it
  finalize_<version>_summary.md    counts only, safe to share
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from evals.dataset.adjudicate import agree
from evals.dataset.answers import NOT_DISCUSSED, NOT_STATED
from evals.dataset.compare_keys import flatten, load_key
from evals.dataset.draft_labels import EVENT_TYPES, load_dispositions
from evals.dataset.fields import load_catalog
from evals.dataset.paths import OUT
from evals.dataset.text import (
    VERTICALS,
    clean_note,
    mask_pii,
    repair_registry_text,
)

# Checks that warn rather than block: a small vertical or a high contested rate
# is worth knowing, not a reason to refuse the key.
MIN_RECORDS_PER_VERTICAL = 10
MAX_CONTESTED_RATE = 0.10


def merge_record(rec_a: dict, rec_b: dict) -> dict:
    """One record from two keys. Values come from A; items where B disagrees
    are listed in ``expected.contested`` (the key used by ``flatten``)."""
    a, b = flatten(rec_a["expected"]), flatten(rec_b["expected"])
    contested = sorted(
        k for k, (_kind, va) in a.items()
        if not agree(va, b.get(k, (None, NOT_STATED))[1])
    )
    merged = json.loads(json.dumps(rec_a))  # deep copy
    merged["expected"]["contested"] = contested
    merged["built_by"] = [rec_a.get("reviewed_by"), rec_b.get("reviewed_by")]
    for key in ("reviewed_by", "reviewed_at", "drafted_by", "drafted_at", "model"):
        merged.pop(key, None)
    # Full campaign descriptions come from the registry export with Windows
    # line endings (108 of 132 in v1), and one (IS-008 in v1) still carried
    # the "gov" Replace-All damage found after v1 was frozen. The short
    # versions sent to the agent were already clean; normalise the stored
    # full text too. Repair is idempotent, so already-repaired text is safe.
    for topic in merged.get("topics", []):
        topic["description"] = clean_note(repair_registry_text(topic.get("description")))
    return merged


def check_record(rec: dict, field_ids: dict[str, list[str]], codes: set[int]) -> list[str]:
    """Problems that make a record unusable as ground truth."""
    rid = rec.get("id", "?")
    problems = []
    exp = rec.get("expected") or {}
    if rec.get("vertical") not in VERTICALS:
        problems.append(f"{rid}: unknown vertical {rec.get('vertical')!r}")
        return problems
    if not str(rec.get("note") or "").strip():
        problems.append(f"{rid}: empty note")
    if mask_pii(rec.get("note") or "") != (rec.get("note") or ""):
        problems.append(f"{rid}: note still contains an email, phone or long number")
    if exp.get("event_type") not in (*EVENT_TYPES, None):
        problems.append(f"{rid}: event_type {exp.get('event_type')!r} not allowed")
    planned = [t["title"] for t in rec.get("topics", [])]
    topics = exp.get("topics") or []
    if [t.get("title") for t in topics] != planned:
        problems.append(f"{rid}: expected topics do not match the planned topics")
    for t in topics:
        if t.get("discussed") and t.get("disposition_code") not in codes:
            problems.append(f"{rid}: topic {t.get('title')!r} has code {t.get('disposition_code')!r}")
        if not t.get("discussed") and t.get("disposition_code") is not None:
            problems.append(f"{rid}: topic {t.get('title')!r} not discussed but has a code")
    fields = exp.get("fields") or {}
    if sorted(fields) != sorted(field_ids[rec["vertical"]]):
        problems.append(f"{rid}: field set is not the {len(field_ids[rec['vertical']])} fields of {rec['vertical']}")
    bad = [k for k, v in fields.items() if v is not None and not isinstance(v, str)]
    if bad:
        problems.append(f"{rid}: non-text values for {bad}")
    return problems


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge two answer keys, check, and freeze.")
    ap.add_argument("--a", required=True, help="run name of the first key (values come from here)")
    ap.add_argument("--b", required=True, help="run name of the second, independent key")
    ap.add_argument("--version", required=True, help="e.g. v1 -- never overwritten once frozen")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", args.version):
        raise SystemExit("--version may contain only letters, digits, '.', '_' and '-'")
    golden = args.out / f"golden_{args.version}.jsonl"
    manifest_path = args.out / f"golden_{args.version}.manifest.json"
    if golden.exists() or manifest_path.exists():
        raise SystemExit(f"{golden.name} is already frozen. Use a new --version.")

    key_a = load_key(args.out / f"reviewed_{args.a}.jsonl")
    key_b = load_key(args.out / f"reviewed_{args.b}.jsonl")
    only_one = sorted(set(key_a) ^ set(key_b))
    if only_one:
        raise SystemExit(f"The keys cover different records ({only_one}); build both from the same sample.")

    catalog = load_catalog()
    field_ids = {v: [f.field_id for f in catalog.fields_for(v)] for v in VERTICALS}
    codes = {int(d["code"]) for d in load_dispositions()}
    merged = [merge_record(key_a[rid], key_b[rid]) for rid in sorted(key_a)]
    problems = [p for rec in merged for p in check_record(rec, field_ids, codes)]

    per_vertical = Counter(r["vertical"] for r in merged)
    items = sum(len(flatten(r["expected"])) for r in merged)
    contested = sum(len(r["expected"]["contested"]) for r in merged)
    strata = Counter(r.get("picked_for") for r in merged)
    warnings = [f"{v}: only {per_vertical[v]} records" for v in VERTICALS
                if per_vertical[v] < MIN_RECORDS_PER_VERTICAL]
    if items and contested / items > MAX_CONTESTED_RATE:
        warnings.append(f"contested rate {contested / items:.1%} is above {MAX_CONTESTED_RATE:.0%}")
    stated = Counter()
    for r in merged:
        for fid, v in r["expected"]["fields"].items():
            stated[(fid, v is not None)] += 1
    never_stated = sorted({fid for fid, _ in stated} - {fid for (fid, s), n in stated.items() if s and n})

    lines = [f"# Finalize '{args.version}' (counts only)", "",
             f"from: {args.a} + {args.b}", f"records: {len(merged)}   "
             f"items: {items}   contested: {contested} ({contested / max(items, 1):.1%})", "",
             "## Records per vertical", ""]
    lines += [f"    {v}  {per_vertical[v]}" for v in VERTICALS]
    lines += ["", "## Records per stratum", ""]
    lines += [f"    {n:>4}  {s}" for s, n in strata.most_common()]
    lines += ["", "## Fields never stated in any record (no positive example to test recall)", ""]
    lines += [f"    {fid}" for fid in never_stated] or ["    none"]
    lines += ["", "## Checks", ""]
    lines += [f"    PROBLEM  {p}" for p in problems] or ["    all records pass"]
    lines += [f"    warning  {w}" for w in warnings]
    summary = args.out / f"finalize_{args.version}_summary.md"
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    if problems:
        raise SystemExit(f"\nNot frozen: {len(problems)} problem(s) above. Summary: {summary}")

    with golden.open("w", encoding="utf-8") as fh:
        for rec in merged:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    manifest = {
        "version": args.version,
        "file": golden.name,
        "sha256": sha256(golden),
        "records": len(merged),
        "items": items,
        "contested": contested,
        "per_vertical": dict(per_vertical),
        "built_from": [args.a, args.b],
        "built_by": merged[0]["built_by"] if merged else [],
        "frozen_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "not_stated_marker": NOT_STATED,
        "not_discussed_marker": NOT_DISCUSSED,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nFrozen: {golden}\nManifest: {manifest_path}")


if __name__ == "__main__":
    main()
