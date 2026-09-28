"""Human review of drafted labels (AIML-2898, steps 3 and 4).

    uv run --with openpyxl python -m evals.dataset.review export --name pilot
    # ... reviewer fills in review_<name>.xlsx ...
    uv run --with openpyxl python -m evals.dataset.review import --name pilot

``export`` turns ``drafts_<name>.jsonl`` into ``review_<name>.xlsx``: one row
per label, each with the draft value, the quote the model gave, and any flags.
The reviewer marks every row Accept or Correct (with the right value).

``import`` reads the sheet back, refuses to proceed while any row is undecided,
and writes:

- ``reviewed_<name>.jsonl`` -- the expected answers, now human-verified
  (contains note text; stays on this machine)
- ``review_<name>_summary.md`` -- how often the drafts had to be corrected,
  and how (counts only, safe to share). This is the pilot gate: it decides
  whether the drafting prompt is good enough to scale to the full sample.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from evals.dataset.answers import (
    NOT_DISCUSSED,
    NOT_STATED,
    derive_topic_status,
    disposition_text,
    latest_drafts,
)
from evals.dataset.draft_labels import (
    DERIVED_FIELDS,
    EVENT_TYPES,
    check_draft,
    labelled_fields,
    load_dispositions,
)
from evals.dataset.fields import load_catalog
from evals.dataset.paths import OUT

DECISIONS = ("Accept", "Correct")
COLUMNS = (
    "record_id", "vertical", "kind", "key", "name", "priority",
    "draft_value", "evidence", "flags", "decision", "corrected_value", "comment",
)
WIDTHS = (10, 8, 11, 34, 28, 8, 40, 40, 30, 11, 30, 30)
FLAG_FILL = PatternFill("solid", fgColor="FCE4D6")
INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
JUDGED_FILL = PatternFill("solid", fgColor="DDEBF7")  # decision made by the judge model


def label_rows(rec: dict, catalog, labels: dict[int, str], flags: list[str]) -> list[list]:
    """Flatten one drafted record into review rows (without decision columns)."""
    draft = rec["draft"]

    def flags_for(prefix: str) -> str:
        return "; ".join(f for f in flags if f.startswith(prefix))

    rows = [[
        rec["id"], rec["vertical"], "event_type", "event_type", "Event type", "",
        draft.get("event_type") or NOT_STATED, draft.get("event_type_evidence", ""),
        flags_for("event_type"),
    ]]
    for t in draft["topics"]:
        rows.append([
            rec["id"], rec["vertical"], "topic", t["title"], "Disposition", "",
            disposition_text(t, labels), t.get("evidence", ""), flags_for(f"topic {t['title']!r}"),
        ])
    by_id = {f.field_id: f for f in catalog.fields_for(rec["vertical"])}
    for f in draft["fields"]:
        spec = by_id[f["field_id"]]
        value = f.get("value")
        rows.append([
            rec["id"], rec["vertical"], "field", spec.field_id, spec.name, spec.priority,
            NOT_STATED if value in (None, "") else value, f.get("evidence", ""),
            flags_for(spec.field_id),
        ])
    return rows


def export(  # noqa: PLR0912
    name: str,
    out: Path,
    force: bool = False,
    prefill: dict[tuple[str, str], tuple[str, str, str, bool]] | None = None,
    reviewer: str = "",
) -> Path:
    """Write the review sheet. ``prefill`` maps (record_id, key) to
    (decision, corrected_value, comment, settled_by_judge) -- used by
    adjudicate.py; rows the judge settled are coloured for a human glance."""
    target = out / f"review_{name}.xlsx"
    if target.exists() and not force:
        raise SystemExit(
            f"{target.name} already exists and may hold review work. Nothing was "
            "overwritten. Pass --force only if you mean to start the review again."
        )
    drafts = latest_drafts(out / f"drafts_{name}.jsonl")
    failed = [d["id"] for d in drafts if d.get("draft") is None]
    if failed:
        raise SystemExit(f"Drafting failed for {failed}; re-run draft_labels first.")
    catalog = load_catalog()
    dispositions = load_dispositions()
    labels = {int(d["code"]): d["label"] for d in dispositions}

    wb = Workbook()
    guide = wb.active
    guide.title = "Guide"
    guide_lines = [
        ("How to review", ""),
        ("1", "Read the note on the Records tab. It is what the agent hears -- nothing else."),
        ("2", "On the Labels tab, set Decision on EVERY row: Accept, or Correct and type the right value."),
        ("3", f'For a field the note does not state, the value is "{NOT_STATED}".'),
        ("4", f'For a topic the note does not discuss, the value is "{NOT_DISCUSSED}".'),
        ("5", "Orange rows were flagged: the model's quote is not in the note. Check those first."),
        ("6", "Remove any customer or contact names you see in the note from the corrected values."),
        ("", ""),
        ("Event types", ", ".join(EVENT_TYPES)),
        ("Disposition codes", "; ".join(f"{c} - {lbl}" for c, lbl in labels.items())),
        ("", ""),
        ("Reviewer name", ""),
    ]
    for row in guide_lines:
        guide.append(row)
    guide["B12"] = reviewer
    guide["B12"].fill = INPUT_FILL
    guide.column_dimensions["A"].width = 20
    guide.column_dimensions["B"].width = 110
    for cell in guide["A"]:
        cell.font = Font(bold=True)

    records = wb.create_sheet("Records")
    records.append(("record_id", "vertical", "picked_for", "planned topics", "note (what the agent hears)", "pre-call objective (context only)"))
    for d in drafts:
        records.append((
            d["id"], d["vertical"], d["picked_for"],
            "\n".join(t["title"] for t in d["topics"]), d["note"], d["objective"],
        ))
    for col, width in zip("ABCDEF", (10, 8, 18, 40, 80, 50), strict=True):
        records.column_dimensions[col].width = width
    for row in records.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")

    sheet = wb.create_sheet("Labels")
    judged_rows: set[int] = set()
    sheet.append(COLUMNS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for d in drafts:
        # Flags are recomputed with the current rules rather than read from the
        # drafts file, so a better check benefits drafts that already exist.
        field_ids = [f.field_id for f in labelled_fields(catalog, d["vertical"])]
        _, flags = check_draft(d["draft"], d, field_ids, set(labels))
        for row in label_rows(d, catalog, labels, flags):
            decision, corrected, comment, judged = (prefill or {}).get(
                (row[0], row[3]), ("", "", "", False)
            )
            sheet.append([*row, decision, corrected, comment])
            if judged:
                judged_rows.add(sheet.max_row)
    last = sheet.max_row
    decision = DataValidation(type="list", formula1=f'"{",".join(DECISIONS)}"', allow_blank=True)
    sheet.add_data_validation(decision)
    decision.add(f"J2:J{last}")
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        for cell in (row[9], row[10], row[11]):
            cell.fill = INPUT_FILL
        if row[8].value:
            for cell in row[:9]:
                cell.fill = FLAG_FILL
        if row[0].row in judged_rows:
            for cell in (row[9], row[10], row[11]):
                cell.fill = JUDGED_FILL
    for i, width in enumerate(WIDTHS, 1):
        sheet.column_dimensions[chr(64 + i)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:L{last}"

    path = target
    wb.save(path)
    print(f"{len(drafts)} records, {last - 1} labels to review -> {path}")
    return path


def _code(value: str) -> int | None:
    m = re.match(r"\s*(\d+)", value)
    return int(m.group(1)) if m else None


def import_review(name: str, out: Path) -> None:  # noqa: PLR0912
    drafts = {d["id"]: d for d in latest_drafts(out / f"drafts_{name}.jsonl")}
    wb = load_workbook(out / f"review_{name}.xlsx", data_only=True)
    reviewer = str(wb["Guide"]["B12"].value or "").strip()
    rows = list(wb["Labels"].iter_rows(min_row=2, values_only=True))

    errors = []
    if not reviewer:
        errors.append("Reviewer name is empty (Guide tab, B12).")
    undecided: Counter = Counter()
    for n, row in enumerate(rows, 2):
        decision, corrected = row[9], row[10]
        if decision not in DECISIONS:
            undecided[row[0]] += 1
        elif decision == "Correct" and (corrected is None or not str(corrected).strip()):
            errors.append(f"Labels row {n}: Correct with no corrected value")
    if undecided:
        errors.append(
            f"{sum(undecided.values())} of {len(rows)} rows have no decision (Accept / Correct), "
            "in records: " + ", ".join(f"{rid} ({n})" for rid, n in sorted(undecided.items()))
        )
    if errors:
        raise SystemExit(
            "Review is not complete -- save and close the sheet, then re-run:\n  "
            + "\n  ".join(errors[:30])
        )

    expected: dict[str, dict] = defaultdict(lambda: {"topics": [], "fields": {}})
    tally: Counter = Counter()
    changes: Counter = Counter()
    for row in rows:
        rid, vertical, kind, key, _name, priority, draft_value, *_rest = row
        decision, corrected = row[9], row[10]
        final = str(draft_value if decision == "Accept" else corrected).strip()
        group = f"field P{priority}" if kind == "field" else kind
        tally[(group, decision)] += 1
        tally[(vertical, decision)] += 1
        if decision == "Correct" and kind == "field":
            was, now = str(draft_value) == NOT_STATED, final == NOT_STATED
            changes["invented a value (should be not stated)" if now and not was
                    else "missed a stated value" if was and not now
                    else "wrong value"] += 1
        exp = expected[rid]
        if kind == "event_type":
            # None = the note does not say; AIML-2702 skips event type for it.
            exp["event_type"] = None if final == NOT_STATED else final
        elif kind == "topic":
            discussed = final.lower() != NOT_DISCUSSED
            exp["topics"].append({"title": key, "discussed": discussed,
                                  "disposition_code": _code(final) if discussed else None})
        else:
            exp["fields"][key] = None if final == NOT_STATED else final

    labels = {int(d["code"]): d["label"] for d in load_dispositions()}
    reviewed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    reviewed_path = out / f"reviewed_{name}.jsonl"
    with reviewed_path.open("w", encoding="utf-8") as fh:
        for rid, exp in expected.items():
            # Derived fields are never labelled; fill them from the answers
            # they restate, so every record still carries its full field set.
            if "U-03" in DERIVED_FIELDS:
                exp["fields"]["U-03"] = derive_topic_status(exp["topics"], labels)
            d = drafts[rid]
            record = {k: v for k, v in d.items() if k not in ("draft", "flags", "problems", "attempts")}
            record.update(expected=exp, drafted_by=d.get("model"), reviewed_by=reviewer,
                          reviewed_at=reviewed_at)
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    lines = [f"# Review '{name}' -- summary (counts only)", "",
             f"records: {len(expected)}   labels: {len(rows)}   reviewer recorded: yes", "",
             "## Draft accepted unchanged", ""]
    groups = sorted({g for g, _ in tally})
    for g in groups:
        acc, cor = tally[(g, "Accept")], tally[(g, "Correct")]
        if acc + cor:
            lines.append(f"    {g:<14} {acc:>5} / {acc + cor:<5} ({acc / (acc + cor):.0%})")
    lines += ["", "## How field drafts were wrong", ""]
    lines += [f"    {n:>5}  {what}" for what, n in changes.most_common()] or ["    none"]
    (out / f"review_{name}_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nReviewed records (contain note text, keep on this machine): {reviewed_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Export or import the label review sheet.")
    ap.add_argument("action", choices=("export", "import"))
    ap.add_argument("--name", default="pilot")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--force", action="store_true", help="export: overwrite an existing review sheet")
    args = ap.parse_args()
    if args.action == "export":
        export(args.name, args.out, args.force)
    else:
        import_review(args.name, args.out)


if __name__ == "__main__":
    main()
