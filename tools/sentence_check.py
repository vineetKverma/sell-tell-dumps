"""What evidence by sentence number did in a saved extract_eval run -- read-only,
counts and ids only, no note text, no model calls.

    cd <repo>
    uv run python C:\\tmp\\sentence_check.py evals\\runs\\extract-<id>

Prints, over every repeat of the golden set:
  - how the notes split (sentences per note, one-sentence notes);
  - cited numbers that are not sentences of the note (ignored by the code);
  - records where a sentence marker such as "[3]" leaked into a summary or field;
  - how much of the note a discussed topic's evidence covers, and how many
    topics cite every sentence of a note that has more than one.
"""

import json
import os
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

from app.extraction.extract import sentences  # noqa: E402
from evals.extract_eval.run import set_cases  # noqa: E402

MARK = re.compile(r"\[\d+\]")


def main() -> None:
    run = Path(sys.argv[1])
    cases = {c.id: c for c in set_cases("golden", None)}
    units = {cid: sentences(c.note) for cid, c in cases.items()}
    counts = [len(u) for u in units.values()]
    print(f"{len(units)} notes: sentences per note min {min(counts)}, median {statistics.median(counts)}, "
          f"max {max(counts)}; one-sentence notes {sum(n == 1 for n in counts)}")
    records = ignored = leaks = topics = whole = 0
    share, leaked_ids, ignored_ids = [], set(), set()
    for raw in sorted(run.glob("raw_golden_r*.jsonl")):
        for line in raw.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            rec = row.get("record")
            if not rec:
                continue
            records += 1
            for numbers in (row.get("ignored_lines") or {}).values():
                ignored += len(numbers)
                ignored_ids.add(row["id"])
            note = cases[row["id"]].note
            texts = [rec.get("executive_summary") or "", *(t.get("summary") or "" for t in rec["topics"]),
                     *(v or "" for v in rec["must_capture"].values())]
            if any(m not in note for text in texts for m in MARK.findall(text)):
                leaks += 1
                leaked_ids.add(row["id"])
            for t in rec["topics"]:
                if t["status"] == "discussed":
                    topics += 1
                    n = len(units[row["id"]])
                    share.append(len(t.get("evidence_lines") or []) / max(n, 1))
                    whole += n > 1 and len(t.get("evidence_lines") or []) == n
    print(f"{records} records, {topics} discussed topics")
    print(f"cited numbers that are not sentences of the note: {ignored}"
          + (f" (cases: {', '.join(sorted(ignored_ids))})" if ignored_ids else ""))
    print(f"records with a sentence marker in a summary or field: {leaks}"
          + (f" (cases: {', '.join(sorted(leaked_ids))})" if leaked_ids else ""))
    if share:
        print(f"share of the note's sentences a discussed topic cites: median {statistics.median(share):.2f}, "
              f"mean {statistics.mean(share):.2f}")
        print(f"topics that cite every sentence of a note with more than one: {whole} of {topics}")


if __name__ == "__main__":
    main()
