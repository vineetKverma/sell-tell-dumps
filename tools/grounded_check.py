"""Replays the "neighbouring sentences" evidence rule on saved extract() runs --
read-only, ids and counts only, no note text, no model calls.

    cd <repo>
    uv run python C:\\tmp\\grounded_check.py <extract run> [<extract run> ...]

For every topic a run kept as discussed, and every code other than 99 it
kept, the sentence numbers saved in the record are checked again with
``grounded`` (two words within one run of neighbouring sentences). Prints how
many would now be rejected; 0 means the rule changes nothing in that run.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from app.extraction.extract import grounded, sentences  # noqa: E402
from evals.agent_eval.cases import load_cases  # noqa: E402

RUNS = Path("evals") / "runs"


def main(runs: list[str]) -> None:
    if not runs:
        raise SystemExit(__doc__)
    units = {c.id: sentences(c.note) for c in load_cases()}
    for run in runs:
        folder = Path(run) if Path(run).exists() else RUNS / run
        files = sorted(folder.glob("raw_golden_r*.jsonl"))
        if not files:
            raise SystemExit(f"{run}: no raw_golden_r*.jsonl")
        topics = codes = 0
        hits = []
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                u = units.get(row["id"])
                for t in ((row.get("record") or {}).get("topics") or []) if u else []:
                    if t.get("status") != "discussed":
                        continue
                    topics += 1
                    if not grounded(t.get("evidence_lines") or [], u):
                        hits.append(f"{f.stem} {row['id']} topic evidence")
                    if t.get("disposition_code") not in (None, 99):
                        codes += 1
                        if not grounded(t.get("outcome_lines") or [], u):
                            hits.append(f"{f.stem} {row['id']} code {t['disposition_code']}")
        print(f"{folder.name}: {len(files)} repeat(s), {topics} discussed topics, {codes} codes kept; "
              f"rejected by the new rule: {len(hits)}")
        for h in hits:
            print("  " + h)


if __name__ == "__main__":
    main(sys.argv[1:])
