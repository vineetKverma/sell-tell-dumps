"""Answer key: contact outcome (U-02) when the note clearly shows a conversation.

    uv run python -m evals.dataset.fix_contact_outcome <evalset.json> <out folder>

The rule (decided from the business's own definitions, not asked of anyone):
a must-capture field is filled when the note CLEARLY SHOWS it and left blank
when filling it would be a guess.

- The must-capture sheet makes U-02 a Priority-1 field, "capture on every
  call", with the values spoke with target / spoke with alternate / no
  contact. Reps never write "I spoke with the target"; they write "Rachel
  said...". So the field can only mean what the note shows.
- The approved event-type rule judges by what happened, not by exact words
  ("if the seller mentions interacting with a person -> Meeting").
- The key left U-02 blank on such notes because OUR labelling instructions
  demanded a verbatim quote for every value (draft_labels.py) -- not a
  business requirement.

So: where the key's event type is Meeting (the rep interacted with someone)
and U-02 is blank and not contested, U-02 becomes "spoke with contact".
Target vs alternate usually cannot be told from a note, so the scorer accepts
either against "spoke with contact" (score.py, field_value_agrees). An
explicit "no contact" or a filled value is never touched. Run it on a key
whose event types already follow the approved rule (golden v1.2), so
"Meeting" means an interaction.

A Phone Call is NOT taken as a conversation: "called, left a voicemail" is a
call with no contact. Those cases keep a blank U-02 until each is read.

Refuses a key that already carries the target version, and writes nothing
when no case changes -- a second run would otherwise replace the manifest's
list of changed cases with an empty one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from evals.agent_eval.score import _stated
from evals.dataset.fix_event_types import stage_args

INTERACTION = ("Meeting",)      # not Phone Call: a call can end at a voicemail
VALUE = "spoke with contact"


def apply(data: dict) -> tuple[dict, list[str]]:
    changed = []
    for case in data["eval_cases"]:
        args = stage_args(case)
        fields = args.get("must_capture")
        if not isinstance(fields, dict):                        # null or missing
            fields = {}
        # Blank as the scorer reads it (score._stated): None, "" or "not stated".
        if (args.get("event_type") in INTERACTION and not _stated(fields.get("U-02"))
                and "U-02" not in (args.get("contested") or [])):
            fields["U-02"] = VALUE
            args["must_capture"] = fields       # only a changed case is touched
            changed.append(case["eval_id"])
    return data, changed


def main() -> None:
    ap = argparse.ArgumentParser(description="Fill U-02 where the key shows an interaction.")
    ap.add_argument("evalset", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--version", default="v1.3", help="label for the new key (default v1.3)")
    args = ap.parse_args()
    raw = args.evalset.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("eval_set_id") == "sellntell_golden_v1.1":
        raise SystemExit("this is golden v1.1: apply fix_event_types (v1.2) first, so Meeting means an interaction")
    if str(data.get("eval_set_id", "")).endswith(f"_{args.version}"):
        raise SystemExit(f"{data['eval_set_id']} already carries {args.version}: this fix was applied; nothing written")
    data, changed = apply(data)
    if not changed:
        raise SystemExit("no case needs this fix; nothing written")
    base = data.get("eval_set_id", "set").rsplit("_v", 1)[0]
    data["eval_set_id"] = f"{base}_{args.version}"
    data["description"] = (data.get("description", "") + f" {args.version}: U-02 set to '{VALUE}' on "
                           f"{len(changed)} cases where the rep interacted with someone.").strip()
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / args.evalset.name
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    norm = lambda b: hashlib.sha256(b.replace(b"\r\n", b"\n")).hexdigest()  # noqa: E731
    manifest = {"version": args.version, "file": out.name, "sha256": norm(out.read_bytes()),
                "from": {"eval_set_id": json.loads(raw)["eval_set_id"], "sha256": norm(raw)},
                "change": f"U-02 -> '{VALUE}' where event type is Meeting and U-02 was blank",
                "rule": "a field is filled when the note clearly shows it, blank when it would be a guess",
                "cases": changed, "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (args.out / f"{out.stem}.{args.version}.manifest.json").write_text(json.dumps(manifest, indent=1) + "\n",
                                                                       encoding="utf-8")
    print(f"written: {out}  ({len(changed)} cases: U-02 -> '{VALUE}')")
    print(f"sha256 (line endings normalised): {manifest['sha256']}")


if __name__ == "__main__":
    main()
