"""One review workbook for the whole golden dataset (AIML-2898 sign-off).

    uv run --with openpyxl python -m evals.dataset.review_workbook

Reads every set in evals/v1/ -- golden_v1, the field top-ups and the
synthetic cases -- and writes evals/v1/golden_v1_review.xlsx:

  Read me    what each set is, how it was built, how to read the tabs
  Coverage   one row per must-capture field (65): how many records state it,
             from real notes or only synthetic ones
  Records    one row per record: the note, event type, topic outcomes, the
             fields it states, anything contested
  Fields     one row per record x field, filterable

Local files only; no model calls. Contains customer notes -- internal only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from evals.dataset.draft_labels import load_dispositions

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "v1"
FIELD_ID = re.compile(r"^(U|MH|HS|HL|IS|TR|IN)-\d{2}$")
VERTICAL_NAMES = {"MH": "Multifamily", "HS": "Hospitality", "HL": "Healthcare",
                  "IS": "Public Sector", "TR": "Trades", "IN": "Industrial"}

SETS = [  # (file stem, label, what it is)
    ("golden_v1", "golden", "90 real notes, 15 per vertical, spread across outcomes"),
    ("golden_topup_v1", "top-up", "real notes picked for vertical fields the 90 never mention (round 1)"),
    ("golden_topup_v2", "top-up", "real notes for the fields round 1 did not confirm (round 2)"),
    ("golden_topup_v3", "top-up", "real notes found with stricter patterns across the whole export (round 3)"),
    ("golden_synthetic_v1", "synthetic", "written dictations for HS-08 and HS-09, which no real note states"),
]

BOLD, WRAP = Font(bold=True), Alignment(wrap_text=True, vertical="top")
HEAD = PatternFill("solid", fgColor="DDEBF7")
CONT = PatternFill("solid", fgColor="FCE4D6")
STATED = PatternFill("solid", fgColor="E2EFDA")
SYNTH = PatternFill("solid", fgColor="FFF2CC")


def load_fields(golden_dir: Path) -> dict[str, dict]:
    out = {}
    for name in ("universal_fields.csv", "vertical_fields.csv"):
        with (golden_dir / name).open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                fid = (row.get("Field ID") or "").strip()
                if FIELD_ID.match(fid):
                    out[fid] = {"name": row["Field"].strip(), "priority": int(row["Priority"]),
                                "vertical": fid.split("-")[0]}
    return out


def load_sets(golden_dir: Path) -> list[tuple[str, str, str, list[dict]]]:
    found = []
    for stem, label, what in SETS:
        path = golden_dir / f"{stem}.jsonl"
        if path.exists():
            recs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
            found.append((stem, label, what, recs))
    if not found or found[0][0] != "golden_v1":
        raise SystemExit(f"golden_v1.jsonl not found in {golden_dir}")
    return found


def stated(value) -> bool:
    return value not in (None, "")


def build(golden_dir: Path) -> Path:
    fields = load_fields(golden_dir)
    sets = load_sets(golden_dir)
    codes = {int(d["code"]): d["label"] for d in load_dispositions()}
    all_recs = [(label, rec) for _, label, _, recs in sets for rec in recs]

    wb = Workbook()

    # Read me
    ws = wb.active
    ws.title = "Read me"
    real = sum(1 for label, _ in all_recs if label != "synthetic")
    rows = [("SellNTell golden dataset v1 -- review copy", ""), ("", ""),
            ("What it is", f"{len(all_recs)} records the voice agent is scored against: {real} real FAR "
                           "notes plus written cases for fields no real note states."),
            ("Source", "Event-9_1_2026 export (notes, planned topics, vertical); Campaign Topics sheet "
                       "(descriptions); must-capture-fields.xlsx (65 fields, P1-P3); app disposition codes."),
            ("How answers were made", "Two independent model builds with roles swapped "
                                      "(gemini-3.8-flash and gemini-3.1-pro-preview): one drafts, the other "
                                      "answers blind, a judge settles disagreements. Where the builds still "
                                      "disagree the item is contested (orange) and not scored."),
            ("", ""), ("Sets", "")]
    for stem, label, what, recs in sets:
        rows.append((f"{stem} ({label})", f"{len(recs)} records -- {what}"))
    rows += [("", ""), ("How to read", ""),
             ("Coverage tab", "One row per field. 'records stating it' counts real notes and synthetic "
                              "cases separately, so you can see what real data covers."),
             ("Records tab", "One row per record: the note, event type, each planned topic's outcome, the "
                             "fields the note states, anything contested. Synthetic rows are yellow."),
             ("Fields tab", "One row per record x field. Filter by set, vertical, field or priority. "
                            "Green = stated; blank = not stated; orange = contested."),
             ("'not stated'", "The note does not say it. The agent should leave it empty; filling it "
                              "counts as invented."),
             ("Event type blank", "The note gives no clue how the contact happened; not scored."),
             ("Campaign type", "Not in the source data; every record carries the placeholder standard_sales."),
             ("", ""), ("Contains customer notes and contact names -- internal only.", "")]
    for row in rows:
        ws.append(row)
    ws["A1"].font = Font(bold=True, size=14)
    for cell in ws["A"][1:]:
        if cell.value:
            cell.font = BOLD
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 120
    for row in ws.iter_rows():
        for c in row:
            c.alignment = WRAP

    # Coverage
    cov = wb.create_sheet("Coverage")
    cov.append(["field", "field name", "vertical", "priority", "records it applies to",
                "stated in real notes", "stated in synthetic cases", "status"])
    applies, real_hits, synth_hits = Counter(), Counter(), Counter()
    for label, rec in all_recs:
        con = set(rec["expected"].get("contested", []))
        for fid, v in rec["expected"]["fields"].items():
            applies[fid] += 1
            if stated(v) and fid not in con and fid != "U-03":
                (synth_hits if label == "synthetic" else real_hits)[fid] += 1
    for fid, f in fields.items():
        if fid == "U-03":
            status = "scored as topics"
        elif real_hits[fid]:
            status = "real notes"
        elif synth_hits[fid]:
            status = "synthetic only"
        else:
            status = "no example"
        cov.append([fid, f["name"], "all" if f["vertical"] == "U" else
                    f"{f['vertical']} - {VERTICAL_NAMES[f['vertical']]}", f"P{f['priority']}",
                    applies[fid], real_hits[fid], synth_hits[fid], status])
        if status == "synthetic only":
            cov.cell(cov.max_row, 8).fill = SYNTH
        elif status == "no example":
            cov.cell(cov.max_row, 8).fill = CONT
    for col, w in zip("ABCDEFGH", (8, 44, 20, 9, 12, 12, 12, 18), strict=True):
        cov.column_dimensions[col].width = w

    # Records
    r = wb.create_sheet("Records")
    r.append(["set", "id", "vertical", "picked for", "planned topics", "note (what the agent hears)",
              "event type", "topic outcomes", "fields the note states", "contested (not scored)"])
    for label, rec in all_recs:
        e = rec["expected"]
        con = set(e.get("contested", []))

        def outcome(t):
            if t["title"] in con:
                return "CONTESTED (not scored)"
            if not t["discussed"]:
                return "not discussed"
            return f"{t['disposition_code']} - {codes.get(t['disposition_code'], '?')}"

        states = [f"{k} {fields[k]['name']} (P{fields[k]['priority']}): {v}"
                  for k, v in e["fields"].items() if stated(v) and k != "U-03" and k not in con]
        event = "CONTESTED" if "event_type" in con else (e["event_type"] or "(not stated)")
        r.append([label, rec["id"], f"{rec['vertical']} - {VERTICAL_NAMES[rec['vertical']]}",
                  rec.get("picked_for", ""), "\n".join(t["title"] for t in rec["topics"]), rec["note"],
                  event, "\n".join(f"{t['title']}: {outcome(t)}" for t in e["topics"]),
                  "\n".join(states) or "(none)", ", ".join(sorted(con))])
        if label == "synthetic":
            for c in r[r.max_row]:
                c.fill = SYNTH
        elif con:
            r.cell(r.max_row, 10).fill = CONT
    for col, w in zip("ABCDEFGHIJ", (10, 11, 18, 16, 34, 70, 14, 44, 60, 22), strict=True):
        r.column_dimensions[col].width = w

    # Fields
    f = wb.create_sheet("Fields")
    f.append(["set", "id", "vertical", "field", "field name", "priority", "expected value", "contested"])
    for label, rec in all_recs:
        con = set(rec["expected"].get("contested", []))
        for k, v in rec["expected"]["fields"].items():
            f.append([label, rec["id"], rec["vertical"], k, fields[k]["name"], fields[k]["priority"],
                      v if stated(v) else "", "yes" if k in con else ""])
            if k in con:
                for c in f[f.max_row]:
                    c.fill = CONT
            elif stated(v):
                f.cell(f.max_row, 7).fill = STATED
    for col, w in zip("ABCDEFGH", (10, 11, 9, 8, 38, 9, 60, 10), strict=True):
        f.column_dimensions[col].width = w

    for sheet in (cov, r, f):
        for c in sheet[1]:
            c.font, c.fill = BOLD, HEAD
        for row in sheet.iter_rows(min_row=2):
            for c in row:
                c.alignment = WRAP
        sheet.freeze_panes = "B2"
        sheet.auto_filter.ref = sheet.dimensions

    out = golden_dir / "golden_v1_review.xlsx"
    wb.save(out)
    real_cov = sum(1 for fid in fields if fid.split("-")[0] != "U" and real_hits[fid])
    synth_only = sorted(fid for fid in fields if not real_hits[fid] and synth_hits[fid])
    print(f"records: {len(all_recs)} ({real} real)  sets: {len(sets)}")
    print(f"vertical fields with real examples: {real_cov}/54   synthetic only: {synth_only or 'none'}")
    print(f"written: {out}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the single review workbook.")
    ap.add_argument("--dir", type=Path, default=GOLDEN_DIR)
    build(ap.parse_args().dir)


if __name__ == "__main__":
    main()
