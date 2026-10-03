"""Does the dataset have a stated example for every must-capture field?

    uv run --with openpyxl python -m evals.dataset.coverage

Reads every set in evals/v1/ (golden, top-ups, synthetic) and the two field
files copied from must-capture-fields.xlsx. A field is covered when at least
one record states it and the two labelling builds did not contest it. U-03 is
derived from the topic outcomes and scored as topics, so it is not counted.

Prints one line per field and ends with COVERAGE PASS (exit 0) only if all 64
countable fields are covered; otherwise COVERAGE FAIL and the missing ids
(exit 1). Counts only -- no note text.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from evals.dataset.review_workbook import GOLDEN_DIR, load_fields, load_sets, stated

DERIVED = {"U-03"}
EXPECTED_FIELDS = 65          # 11 universal + 9 x 6 verticals, per the sheet
PER_VERTICAL = 9


def coverage(golden_dir: Path) -> tuple[dict, Counter, Counter, list[str]]:
    fields = load_fields(golden_dir)
    real, synth = Counter(), Counter()
    sets = load_sets(golden_dir)
    for _, label, _, recs in sets:
        for rec in recs:
            con = set(rec["expected"].get("contested", []))
            for fid, v in rec["expected"]["fields"].items():
                if stated(v) and fid not in con and fid not in DERIVED:
                    (synth if label == "synthetic" else real)[fid] += 1
    return fields, real, synth, [s[0] for s in sets]


def main() -> None:
    ap = argparse.ArgumentParser(description="Check every must-capture field has an example.")
    ap.add_argument("--dir", type=Path, default=GOLDEN_DIR)
    args = ap.parse_args()
    fields, real, synth, sets = coverage(args.dir)

    problems = []
    if len(fields) != EXPECTED_FIELDS:
        problems.append(f"field files list {len(fields)} fields, expected {EXPECTED_FIELDS}")
    per_v = Counter(f["vertical"] for f in fields.values())
    if per_v.get("U") != 11 or any(per_v.get(v) != PER_VERTICAL for v in ("MH", "HS", "HL", "IS", "TR", "IN")):
        problems.append(f"fields per group: {dict(per_v)}")

    print(f"sets read: {', '.join(sets)}")
    missing, synth_only = [], []
    for fid, f in fields.items():
        if fid in DERIVED:
            status = "scored as topics"
        elif real[fid]:
            status = "real"
        elif synth[fid]:
            status = "synthetic only"
            synth_only.append(fid)
        else:
            status = "MISSING"
            missing.append(fid)
        print(f"  {fid:<6} P{f['priority']}  real {real[fid]:>3}  synthetic {synth[fid]:>2}  {status}")

    countable = [fid for fid in fields if fid not in DERIVED]
    vert = [fid for fid in countable if not fid.startswith("U-")]
    print(f"\nuniversal covered by real notes: {sum(1 for f in countable if f.startswith('U-') and real[f])}/10 "
          f"(+U-03 as topics)")
    print(f"vertical covered by real notes:  {sum(1 for f in vert if real[f])}/{len(vert)}")
    print(f"synthetic only: {synth_only or 'none'}")
    if problems or missing:
        for p in problems:
            print(f"PROBLEM {p}")
        print(f"COVERAGE FAIL: {len(missing)} field(s) with no example: {missing}")
        sys.exit(1)
    print(f"COVERAGE PASS: all {len(countable)} countable fields have an example")


if __name__ == "__main__":
    main()
