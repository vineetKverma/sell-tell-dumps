"""Named campaigns one by one across saved extract_eval runs -- read-only, ids,
statuses and codes only, no note text, no model calls.

    cd <repo>
    uv run python C:\\tmp\\case_report.py evals\\runs\\extract-<before> evals\\runs\\extract-<after>

For each case below, every planned campaign: what the current answer key
says, and what each run's repeats gave (status and code). The key is read as
it is now, so a run made on an older key is shown against the new one.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

from evals.extract_eval.run import set_cases  # noqa: E402

CASES = ("HL-007", "HS-013", "HL-010", "MH-006", "MH-015", "IN-005", "IN-013", "IS-003", "IS-007")
SHORT = {"discussed": "disc", "not_discussed": "not", "unconfirmed": "unconf"}


def main() -> None:
    runs = [Path(a) for a in sys.argv[1:] if not a.startswith("--")]
    only = next((a.split("=", 1)[1].split(",") for a in sys.argv[1:] if a.startswith("--only=")), CASES)
    cases = {c.id: c for c in set_cases("golden", None)}
    got: dict = {}
    for run in runs:
        for raw in sorted(run.glob("raw_golden_r*.jsonl")):
            for line in raw.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                if row["id"] in only:
                    rec = row.get("record") or {}
                    got.setdefault((run.name, row["id"]), []).append(
                        (rec.get("event_type"), {t["topic"]: t for t in rec.get("topics", [])}))
    for cid in only:
        case = cases[cid]
        print(f"\n{cid} | key: event type {case.event_type}" + (" (contested)" if "event_type" in case.contested else ""))
        for run in runs:
            print(f"    {run.name}: event type {[e for e, _ in got.get((run.name, cid), [])]}")
        for exp in case.topics:
            mark = " (contested, not scored)" if exp["topic"] in case.contested else ""
            want = f"discussed, code {exp['disposition_code']}" if exp["discussed"] else "not discussed"
            print(f"  {exp['topic']} | key: {want}{mark}")
            for run in runs:
                cells = []
                for _, topics in got.get((run.name, cid), []):
                    t = topics.get(exp["topic"]) or {}
                    code = t.get("disposition_code")
                    cells.append(SHORT.get(t.get("status"), "?") + (f" {code}" if code is not None else ""))
                right = sum((c.startswith("disc") and exp["discussed"] and c == f"disc {exp['disposition_code']}")
                            or (not c.startswith("disc") and not exp["discussed"]) for c in cells)
                print(f"    {run.name}: {cells}  right {right}/{len(cells)}")


if __name__ == "__main__":
    main()
