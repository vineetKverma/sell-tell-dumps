"""Over-claimed topics in runs, with how many sentences the case's note has --
read-only, ids and numbers only, no note text, no model calls.

    cd <repo>
    uv run python C:\\tmp\\overclaim_units.py <run> [<run> ...]

A run is a folder under evals/runs/ holding scores.json (an agent run) or
scores_golden.json (an extract run). An over-claim is a topic the key says
was not discussed that the run marked discussed. "units" is the number of
sentences extract() numbers the note into; 1 means the note has no sentence
end, so citing it counts for any topic.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
import json

sys.path.insert(0, str(Path.cwd()))
from app.extraction import sentences  # noqa: E402
from evals.agent_eval.cases import load_cases  # noqa: E402

RUNS = Path("evals") / "runs"


def main(runs: list[str]) -> None:
    if not runs:
        raise SystemExit(__doc__)
    cases = {c.id: c for c in load_cases()}
    units = {cid: len(sentences(c.note)) for cid, c in cases.items()}
    print(f"golden notes: {len(units)}, with one unit: {sum(n == 1 for n in units.values())}")
    for run in runs:
        folder = Path(run) if Path(run).exists() else RUNS / run
        path = next((folder / f for f in ("scores.json", "scores_golden.json") if (folder / f).exists()), None)
        if path is None:
            raise SystemExit(f"{run}: no scores.json or scores_golden.json")
        reps = json.loads(path.read_text(encoding="utf-8"))["cases"]
        hits, of = Counter(), 0
        for rep in reps:
            for s in rep:
                if not s:
                    continue
                for i, t in enumerate(s["topics"], 1):
                    if t["expected"] == "not discussed":
                        of += 1
                        if t["actual"] == "discussed":
                            hits[(s["id"], i)] += 1
        print(f"\n{folder.name}: {sum(hits.values())} over-claimed of {of} not-discussed topic scores "
              f"over {len(reps)} repeat(s)")
        for (cid, i), n in sorted(hits.items()):
            print(f"  {cid} topic {i}: {n} of {len(reps)} repeats, note units {units.get(cid, '?')}")


if __name__ == "__main__":
    main(sys.argv[1:])
