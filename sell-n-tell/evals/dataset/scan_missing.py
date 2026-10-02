"""Confirm whether a field is really absent from the export (AIML-2898 top-up).

The top-up rounds drew only from the sampling pool: notes whose planned topics
all have a Campaign Topics description, de-duplicated, healthcare notes naming
a patient or resident removed. "No note confirmed it" therefore meant "not in
that pool". This scans EVERY note of the field's vertical, with the field's
broad keyword pattern and its strict detail pattern, and says where the strict
matches sit:

    uv run --with pandas --with pyxlsb --with openpyxl --with pyarrow \\
        python -m evals.dataset.scan_missing --fields HL-05,HL-09,HS-08,HS-09,MH-04,TR-06

Counts only (safe to share): evals/data/out/scan_missing_summary.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.dataset.sample import build_pool
from evals.dataset.sample_topup import PATTERNS, STRICT, matches, vertical_of
from evals.dataset.source import OUT, RAW, load_events, load_registry
from evals.dataset.text import HEALTHCARE_PERSON, clean_note


def labelled_rows(out: Path) -> set[int]:
    """Source rows already labelled by any run (every sample file)."""
    rows: set[int] = set()
    for path in out.glob("sample_*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.add(int(json.loads(line)["source_row"]))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan the whole export for the missing fields.")
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--fields", required=True)
    ap.add_argument("--seed", type=int, default=2898)
    args = ap.parse_args()
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    unknown = sorted(set(fields) - set(PATTERNS))
    if unknown:
        raise SystemExit(f"no pattern for {unknown}")

    ev = load_events(args.raw)
    allnotes = ev[ev["vertical"].notna()].copy()
    allnotes["note_clean"] = allnotes["note"].map(clean_note)
    allnotes = allnotes[allnotes["note_clean"].str.len() > 0]
    dup = allnotes["note_clean"].str.lower().duplicated()
    patient = (allnotes["vertical"] == "HL") & allnotes["note_clean"].str.lower().str.contains(
        HEALTHCARE_PERSON, regex=True)
    described_pool, _ = build_pool(ev, load_registry(args.raw), True, args.seed)
    in_pool = set(described_pool.index)
    done = labelled_rows(args.out)

    lines = ["# Scan for missing fields -- whole export (counts only)", "",
             f"notes with text and a vertical: {len(allnotes):,}", "",
             "strict = every detail pattern matches (see STRICT in sample_topup.py)", "",
             "| field | notes in vertical | broad match | strict match | of strict: in described pool, "
             "not yet labelled | undescribed topics only | duplicate | patient/resident (HL, excluded by policy) "
             "| already labelled |",
             "|---|---|---|---|---|---|---|---|---|"]
    for fid in fields:
        sub = allnotes[allnotes["vertical"] == vertical_of(fid)]
        broad = sub["note_clean"].map(lambda t, f=fid: matches(f, t, False))
        strict = sub["note_clean"].map(lambda t, f=fid: matches(f, t, True)) if fid in STRICT else broad
        s_idx = sub.index[strict]
        n_dup = int(dup.loc[s_idx].sum())
        n_pat = int(patient.loc[s_idx].sum())
        n_done = sum(int(i) in done for i in s_idx)
        n_pool = sum(i in in_pool and int(i) not in done for i in s_idx)
        n_undesc = sum(i not in in_pool and not dup.loc[i] and not patient.loc[i] and int(i) not in done
                       for i in s_idx)
        lines.append(f"| {fid} | {len(sub):,} | {int(broad.sum()):,} | {len(s_idx):,} | {n_pool:,} "
                     f"| {n_undesc:,} | {n_dup:,} | {n_pat:,} | {n_done:,} |")
    lines += ["", "A strict match is still only a candidate; labelling decides. Zero strict matches "
              "outside the excluded columns means the export has no usable note for that field."]
    path = args.out / "scan_missing_summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nwritten: {path}")


if __name__ == "__main__":
    main()
