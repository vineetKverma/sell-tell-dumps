"""Golden set v1.1 -> v1.2: event types per the approved rule (Jeremy).

    uv run python -m evals.dataset.fix_event_types <golden_v1.1 evalset.json> <out folder>

Why: the labelling rule left event type blank when a note did not say HOW
the contact happened (draft_labels.py). The scorer later read every blank as
"no person -> On-site visit". The approved rule is "if the seller mentions
interacting with a person, Meeting; otherwise On-Site Visit" -- so a blank on
a note where the rep dealt with someone is scored against the rule.

The 17 cases below were reviewed one by one (ids only here; no note text).
An interaction with nobody named ("we discussed...") also counts. That was an
assumption when this ran; the business confirmed it on 2026-10-14, with one
exception (front desk or gatekeeper only is an On-site visit), which key v1.4
applies on top of this one. So --named-only is no longer needed; it is kept
only to reproduce the alternative.

Refuses unless every listed case is still blank and not contested, and the
input is the v1.1 file it was reviewed against.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

SOURCE_SET_ID = "sellntell_golden_v1.1"
NAMED_PERSON = ["HL-003", "HS-004", "IN-013", "IS-008", "IS-009", "IS-012",
                "MH-002", "MH-009", "TR-012", "TR-014"]
INTERACTION_NOBODY_NAMED = ["HL-010", "HL-015", "HS-003", "IN-009", "IN-015", "MH-006", "TR-007"]
TO_MEETING = NAMED_PERSON + INTERACTION_NOBODY_NAMED
RULE = ("Phone Call if the rep says it was a call; Meeting if the rep mentions interacting with anyone, "
        "named or not; otherwise On-site visit (including a person not available, or no interaction).")


def _norm_sha(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def stage_args(case: dict) -> dict:
    turn = case["conversation"][0]
    return next(t for t in turn["intermediate_data"]["tool_uses"] if t["name"] == "stage_visit_notes")["args"]


def apply(data: dict, to_meeting: list[str] = TO_MEETING) -> dict:
    if data.get("eval_set_id") != SOURCE_SET_ID:
        raise SystemExit(f"expected {SOURCE_SET_ID}, got {data.get('eval_set_id')!r}: reviewed against v1.1 only")
    by_id = {c["eval_id"]: c for c in data["eval_cases"]}
    problems = []
    for cid in to_meeting:
        if cid not in by_id:
            problems.append(f"{cid}: not in the set")
            continue
        args = stage_args(by_id[cid])
        if args.get("event_type") is not None:
            problems.append(f"{cid}: event type is {args['event_type']!r}, not blank")
        if "event_type" in (args.get("contested") or []):
            problems.append(f"{cid}: event type is contested")
    if problems:
        raise SystemExit("not applied:\n  " + "\n  ".join(problems))
    for cid in to_meeting:
        stage_args(by_id[cid])["event_type"] = "Meeting"
    data["eval_set_id"] = "sellntell_golden_v1.2"
    data["name"] = "SellNTell golden set v1.2"
    data["description"] = (data.get("description", "") + f" v1.2: event type of {len(to_meeting)} cases set to "
                           "Meeting per the approved rule (see the manifest).").strip()
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Golden set v1.1 -> v1.2 (event types per the approved rule).")
    ap.add_argument("evalset", type=Path, help="golden_v1.evalset.json (v1.1)")
    ap.add_argument("out", type=Path, help="folder to write golden_v1.evalset.json (v1.2) and its manifest")
    ap.add_argument("--named-only", action="store_true",
                    help="only the named-person cases (not needed: the business confirmed that "
                         "'we discussed...' counts)")
    args = ap.parse_args()
    raw = args.evalset.read_bytes()
    changes = NAMED_PERSON if args.named_only else TO_MEETING
    data = apply(json.loads(raw.decode("utf-8")), changes)
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / "golden_v1.evalset.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    manifest = {
        "version": "v1.2", "file": out.name, "sha256": _norm_sha(out.read_bytes()),
        "from": {"version": "v1.1", "sha256": _norm_sha(raw)},
        "change": "event type set to Meeting", "rule": RULE,
        "named_person": [c for c in NAMED_PERSON if c in changes],
        "interaction_nobody_named": [c for c in INTERACTION_NOBODY_NAMED if c in changes],
        "assumption": None if args.named_only else
        "'we discussed...' with nobody named counts as interacting with a person -- confirmed by the business "
        "on 2026-10-14 (key v1.4 adds the front-desk exception)",
        "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (args.out / "golden_v1.2.manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"written: {out}  ({len(changes)} cases -> Meeting)")
    print(f"sha256 (line endings normalised): {manifest['sha256']}")


if __name__ == "__main__":
    main()
