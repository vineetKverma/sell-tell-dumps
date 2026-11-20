"""What the review's two extract() fixes change on the golden set -- read-only,
ids and counts only, no note text, no model calls.

    cd <repo>
    uv run python C:\\tmp\\split_check.py [<extract run> ...]

1. The splitter: every golden note split with the rule before ("sq.", "ft."
   and "no." ended a sentence) and with the current ``sentences``; prints the
   notes whose units differ, with the unit counts.
2. With extract runs: the saved summaries (topic and executive) that still
   hold a bracketed number -- the glued or out-of-range citations the old
   strip let through, which the current one removes.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from app.extraction.extract import sentences  # noqa: E402
from evals.agent_eval.cases import load_cases  # noqa: E402

RUNS = Path("evals") / "runs"
_OLD_NOT_AN_END = "".join(rf"(?<!\b{re.escape(a)})" for a in
                          ("mr.", "mrs.", "ms.", "dr.", "e.g.", "i.e.", "vs.", "approx."))
_OLD_END = re.compile(rf"(?<=[.!?]){_OLD_NOT_AN_END}\s+", re.IGNORECASE)
_BRACKET_NUMBER = re.compile(r"\[\d+(?:\s*[,;\-–]\s*\d+)*\]")


def old_sentences(note: str) -> list[str]:
    return [s.strip() for line in (note or "").splitlines() for s in _OLD_END.split(line) if s.strip()]


def main(runs: list[str]) -> None:
    cases = load_cases()
    changed = [(c.id, len(old_sentences(c.note)), len(sentences(c.note)))
               for c in cases if old_sentences(c.note) != sentences(c.note)]
    print(f"splitter: {len(changed)} of {len(cases)} golden notes split differently")
    for cid, before, after in changed:
        print(f"  {cid}: {before} units before, {after} now")
    for run in runs:
        folder = Path(run) if Path(run).exists() else RUNS / run
        files = sorted(folder.glob("raw_golden_r*.jsonl"))
        if not files:
            raise SystemExit(f"{run}: no raw_golden_r*.jsonl")
        total, hits = 0, []
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                rec = row.get("record") or {}
                texts = [("executive", rec.get("executive_summary") or "")] + [
                    (t.get("topic", "?"), t.get("summary") or "") for t in rec.get("topics") or []]
                for where, text in texts:
                    if text:
                        total += 1
                        if _BRACKET_NUMBER.search(text):
                            hits.append(f"{f.stem} {row['id']} {where}")
        print(f"{folder.name}: {len(hits)} of {total} saved summaries hold a bracketed number")
        for h in hits:
            print("  " + h)


if __name__ == "__main__":
    main(sys.argv[1:])
