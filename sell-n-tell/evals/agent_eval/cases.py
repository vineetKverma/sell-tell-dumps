"""Load the golden eval set and the must-capture field priorities.

Both live next to each other in ``evals/v1/``:

  golden_v1.evalset.json   90 ADK EvalCases (the note, the session state, and
                           the expected stage_visit_notes arguments)
  universal_fields.csv     the 11 universal fields, with priority 1-3
  vertical_fields.csv      the 9 fields of each of the six verticals

Nothing here needs ADK: the eval set is read as plain JSON, so the harness runs
on any ADK version and the same file still loads into ``adk eval`` later.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "v1"
EVALSET = GOLDEN_DIR / "golden_v1.evalset.json"
EXPECTED_CASES = 90

# U-03 restates the topic outcomes, which are scored as topics. Scoring it as a
# field too would count every topic answer twice.
DERIVED_FIELDS = frozenset({"U-03"})

_FIELD_ID = re.compile(r"^(U|MH|HS|HL|IS|TR|IN)-\d{2}$")


@dataclass(frozen=True)
class Case:
    id: str
    vertical: str
    note: str
    planned_topics: list[str]
    event_type: str | None                 # None = the note gives no clue
    topics: list[dict]                     # [{topic, discussed, disposition_code}]
    fields: dict[str, str | None]          # field id -> value, None = not stated
    contested: frozenset[str] = field(default_factory=frozenset)


def load_priorities(golden_dir: Path = GOLDEN_DIR) -> dict[str, int]:
    """Field id -> priority (1, 2 or 3). The vertical sheet interleaves one
    heading row per vertical; those rows carry no field id and are skipped."""
    out: dict[str, int] = {}
    for name in ("universal_fields.csv", "vertical_fields.csv"):
        with (golden_dir / name).open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                fid = (row.get("Field ID") or "").strip()
                if _FIELD_ID.match(fid):
                    out[fid] = int(row["Priority"])
    return out


def _case(raw: dict) -> Case:
    turn = raw["conversation"][0]
    note = "".join(p.get("text", "") for p in turn["user_content"]["parts"])
    call = next(t for t in turn["intermediate_data"]["tool_uses"]
                if t["name"] == "stage_visit_notes")
    args = call["args"]
    state = raw["session_input"]["state"]
    return Case(
        id=raw["eval_id"],
        vertical=state["vertical"],
        note=note,
        planned_topics=list(state["planned_topics"]),
        event_type=args.get("event_type"),
        topics=list(args.get("topics") or []),
        fields=dict(args.get("must_capture") or {}),
        contested=frozenset(args.get("contested") or []),
    )


def load_cases(path: Path = EVALSET, strict: bool = True) -> list[Case]:
    """All cases in the eval set. ``strict`` refuses a set that is not the
    full golden_v1 (wrong count, duplicate ids, a case with no expected call)
    so a partial or edited file can never produce a baseline."""
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = [_case(c) for c in data["eval_cases"]]
    if strict:
        ids = [c.id for c in cases]
        if len(ids) != EXPECTED_CASES or len(set(ids)) != len(ids):
            raise SystemExit(
                f"{path.name}: expected {EXPECTED_CASES} unique cases, found "
                f"{len(ids)} ({len(set(ids))} unique). Not the golden_v1 set."
            )
    return cases
