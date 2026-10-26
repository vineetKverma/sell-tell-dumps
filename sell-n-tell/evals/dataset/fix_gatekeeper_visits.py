"""Golden set v1.3 -> v1.4: event types per the rule as the business confirmed it.

    uv run python -m evals.dataset.fix_gatekeeper_visits <golden_v1.3 evalset.json> <out folder>

The rule (Tobi, 2026-10-14, answering for Jeremy): a Meeting is a selling
conversation with the customer; when the rep went to the property but did
not speak with the customer or decision maker -- even if they spoke to
someone, e.g. the front desk or a gatekeeper -- it is an On-site visit.

Our reading, decided from the business's own definitions rather than asked:
a Meeting is a conversation about the business with a customer contact, the
decision maker or another contact such as a manager or supervisor. That
matches the must-capture sheet, where U-02 (contact outcome) is "spoke with
target", "spoke with alternate" or "no contact": a contact is the target or
an alternate, never the front desk.

All 67 Meeting cases of v1.3 were reread against it (ids only here; no note
text):

- HS-007: the rep spoke only to the front desk; the contact was not
  available. Becomes On-site visit. Its U-02 ("spoke with alternate" for the
  front-desk person) no longer fits the reading and is marked contested.
- HL-011: someone seen at check-in passes on account feedback while the rep
  waits for the contact -- front desk or contact cannot be told. Event type
  and U-02 (set only because it was a Meeting, v1.3) are marked contested.
- TR-006 is the borderline case kept as Meeting: a pricing conversation with
  two customer staff who are not the right contact for that product.

On-site visits and Phone Calls need no reread: the old rule ("interacting
with anyone") was wider, so nothing becomes a Meeting.

Refuses unless the input is v1.3 and every listed case still has the value it
was reviewed with.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from evals.dataset.fix_event_types import stage_args

SOURCE_SET_ID = "sellntell_golden_v1.3"
TO_ON_SITE = {"HS-007": "Meeting"}                 # id: event type it was reviewed with
CONTEST = {"HS-007": ["U-02"], "HL-011": ["event_type", "U-02"]}
KEPT_BORDERLINE = ["TR-006"]
RULE = ("Phone Call if the rep says it was a call; Meeting if the rep had a conversation about the business "
        "with a customer contact (the decision maker or another contact such as a manager or supervisor); "
        "otherwise On-site visit, including front desk or gatekeeper only, samples left, or the contact not "
        "available.")


def _norm_sha(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def apply(data: dict) -> dict:
    if data.get("eval_set_id") != SOURCE_SET_ID:
        raise SystemExit(f"expected {SOURCE_SET_ID}, got {data.get('eval_set_id')!r}: reviewed against v1.3 only")
    by_id = {c["eval_id"]: c for c in data["eval_cases"]}
    problems = [f"{cid}: not in the set" for cid in {*TO_ON_SITE, *CONTEST} if cid not in by_id]
    for cid, was in TO_ON_SITE.items():
        if cid in by_id and stage_args(by_id[cid]).get("event_type") != was:
            problems.append(f"{cid}: event type is {stage_args(by_id[cid]).get('event_type')!r}, not {was!r}")
    if problems:
        raise SystemExit("not applied:\n  " + "\n  ".join(sorted(problems)))
    for cid in TO_ON_SITE:
        stage_args(by_id[cid])["event_type"] = "On-site visit"
    for cid, items in CONTEST.items():
        args = stage_args(by_id[cid])
        args["contested"] = list(dict.fromkeys([*(args.get("contested") or []), *items]))
    data["eval_set_id"] = "sellntell_golden_v1.4"
    data["name"] = "SellNTell golden set v1.4"
    data["description"] = (data.get("description", "") + " v1.4: event types per the rule as the business "
                           "confirmed it -- front desk only is an On-site visit (see the manifest).").strip()
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Golden set v1.3 -> v1.4 (front desk only is an On-site visit).")
    ap.add_argument("evalset", type=Path, help="golden_v1.evalset.json (v1.3)")
    ap.add_argument("out", type=Path, help="folder to write golden_v1.evalset.json (v1.4) and its manifest")
    args = ap.parse_args()
    raw = args.evalset.read_bytes()
    data = apply(json.loads(raw.decode("utf-8")))
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / "golden_v1.evalset.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    manifest = {
        "version": "v1.4", "file": out.name, "sha256": _norm_sha(out.read_bytes()),
        "from": {"version": "v1.3", "sha256": _norm_sha(raw)},
        "rule": RULE, "rule_source": "Tobi, 2026-10-14 (answering for Jeremy); reading as in the script",
        "to_on_site_visit": sorted(TO_ON_SITE), "contested": CONTEST, "kept_as_meeting_borderline": KEPT_BORDERLINE,
        "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (args.out / "golden_v1.4.manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"written: {out}  (to On-site visit: {', '.join(TO_ON_SITE)}; contested: "
          f"{', '.join(f'{k} {v}' for k, v in CONTEST.items())})")
    print(f"sha256 (line endings normalised): {manifest['sha256']}")


if __name__ == "__main__":
    main()
