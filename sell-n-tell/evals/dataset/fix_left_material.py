"""Golden set v1.4 -> v1.5: one rule for "left, nobody spoken to".

    uv run python -m evals.dataset.fix_left_material <golden_v1.4 evalset.json> <out folder>

The business's answers (Jeremy, 2026-11-13, to four questions):

1. The rep speaks to no one but leaves something about a campaign (a guide or
   flyer for the contact, information at the door, a voicemail that mentions
   it): the campaign is NOT discussed.
2. The rep gives the customer a quote: Create Opportunity (code 1), until the
   outcome list gets an option of its own.
3. The customer prefers another brand or vendor for a campaign's products: the
   campaign is discussed, with code 5 (Buying from preferred vendor already).
4. The rep meets one contact in person, who then phones the decision maker,
   and the business conversation happens on that call: a Meeting.

The key was split two and two on the first (13 of the 90 notes mention leaving
or delivering something; in four the rep spoke to no one about the campaign).
The other three answers confirm what the key already says, so they are only
checked here (ids only; no note text):

- HL-007, HS-013: material left, the contact busy or away. Their campaign was
  "discussed, 99" and becomes not discussed.
- IN-005 (material at the door, no answer) and IS-007 (a voicemail that
  referenced campaigns) were already not discussed.
- MH-006 (a quote given) is code 1; HL-010 (another brand preferred) is
  discussed with code 5; IS-003 (met on site, the engineer phoned) is a
  Meeting. Unchanged.

Refuses unless the input is v1.4 and every listed entry still has the value it
was reviewed with. U-03 (the topic statuses as text, a derived field) is kept
in step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from evals.dataset.fix_event_types import stage_args

SOURCE_SET_ID = "sellntell_golden_v1.4"
# id: the campaign that was "discussed, 99" and becomes not discussed
TO_NOT_DISCUSSED = {"HL-007": "HC Improve the Room", "HS-013": "2026 Q2 HOS $0 Spend - Pool Chemicals"}
# Reviewed and unchanged: (id, campaign, discussed, code)
CONFIRMED_TOPICS = [
    ("IN-005", "2026 Q2 Everyday Essentials - IND", False, None),
    ("IS-007", "[L3J] PS Everyday Essentials - Q2 2026", False, None),
    ("IS-007", "Full Suites Appliances - Q2 2026 PS", False, None),
    ("MH-006", "Q2 26 MF Full Suites Appliances", True, 1),
    ("HL-010", "HC Q2 Ecolab Scientific Clean", True, 5),
]
CONFIRMED_EVENT_TYPES = {"IS-003": "Meeting"}
NONE_FITS = 99
RULE = ("A campaign is discussed only if the rep talked with someone at the customer about its offer, products "
        "or brand, the customer's reaction included (a refusal, or preferring another brand or vendor: code 5). "
        "Material, a flyer or a voicemail left with no one spoken to is not discussed. A quote the rep gave is "
        "code 1. A visit where the rep met a contact in person is a Meeting even when the decision maker was "
        "phoned during it.")


def _norm_sha(raw: bytes) -> str:
    return hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()


def _topic(args: dict, title: str) -> dict | None:
    return next((t for t in args.get("topics") or [] if t.get("topic") == title), None)


def apply(data: dict) -> dict:
    if data.get("eval_set_id") != SOURCE_SET_ID:
        raise SystemExit(f"expected {SOURCE_SET_ID}, got {data.get('eval_set_id')!r}: reviewed against v1.4 only")
    by_id = {c["eval_id"]: c for c in data["eval_cases"]}
    wanted = [(cid, title, True, NONE_FITS) for cid, title in TO_NOT_DISCUSSED.items()] + CONFIRMED_TOPICS
    problems = [f"{cid}: not in the set" for cid in sorted({c for c, *_ in wanted} | set(CONFIRMED_EVENT_TYPES))
                if cid not in by_id]
    for cid, title, discussed, code in wanted:
        if cid not in by_id:
            continue
        t = _topic(stage_args(by_id[cid]), title)
        if t is None:
            problems.append(f"{cid}: no campaign {title!r}")
        elif (bool(t.get("discussed")), t.get("disposition_code")) != (discussed, code):
            problems.append(f"{cid}: {title!r} is discussed={t.get('discussed')!r} code={t.get('disposition_code')!r}, "
                            f"not discussed={discussed!r} code={code!r}")
    for cid, was in CONFIRMED_EVENT_TYPES.items():
        if cid in by_id and stage_args(by_id[cid]).get("event_type") != was:
            problems.append(f"{cid}: event type is {stage_args(by_id[cid]).get('event_type')!r}, not {was!r}")
    if problems:
        raise SystemExit("not applied:\n  " + "\n  ".join(sorted(problems)))
    for cid, title in TO_NOT_DISCUSSED.items():
        args = stage_args(by_id[cid])
        t = _topic(args, title)
        t["discussed"], t["disposition_code"] = False, None
        fields = args.get("must_capture")
        if isinstance(fields, dict) and isinstance(fields.get("U-03"), str):
            # the derived text: "<campaign>: discussed - 99 ..." between " | " separators
            fields["U-03"] = " | ".join(f"{title}: not discussed" if part.startswith(f"{title}: ") else part
                                        for part in fields["U-03"].split(" | "))
    data["eval_set_id"] = "sellntell_golden_v1.5"
    data["name"] = "SellNTell golden set v1.5"
    data["description"] = (data.get("description", "") + " v1.5: material or a voicemail left with no one spoken "
                           "to is not discussed (see the manifest).").strip()
    return data


def main() -> None:
    ap = argparse.ArgumentParser(description="Golden set v1.4 -> v1.5 (left, nobody spoken to: not discussed).")
    ap.add_argument("evalset", type=Path, help="golden_v1.evalset.json (v1.4)")
    ap.add_argument("out", type=Path, help="folder to write golden_v1.evalset.json (v1.5) and its manifest")
    args = ap.parse_args()
    raw = args.evalset.read_bytes()
    data = apply(json.loads(raw.decode("utf-8")))
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / "golden_v1.evalset.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    manifest = {
        "version": "v1.5", "file": out.name, "sha256": _norm_sha(out.read_bytes()),
        "from": {"version": "v1.4", "sha256": _norm_sha(raw)},
        "rule": RULE, "rule_source": "Jeremy, 2026-11-13, answering four questions (see the script)",
        "to_not_discussed": TO_NOT_DISCUSSED,
        "confirmed_unchanged": {"topics": [list(row) for row in CONFIRMED_TOPICS], "event_types": CONFIRMED_EVENT_TYPES},
        "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (args.out / "golden_v1.5.manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"written: {out}  (to not discussed: {', '.join(f'{k} {v!r}' for k, v in TO_NOT_DISCUSSED.items())})")
    print(f"sha256 (line endings normalised): {manifest['sha256']}")


if __name__ == "__main__":
    main()
