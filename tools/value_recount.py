"""How many "wrong" field values in a saved extract_eval run are only reworded
-- read-only, no model calls.

    cd <repo>
    uv run python C:\\tmp\\value_recount.py evals\\runs\\extract-<id> [--show]

The run's own scorer counts a value right only if it equals the key's wording
or contains it. Here every value the scorer counted wrong is sorted into:

  reworded    most of the key's words are there, or the text is nearly the same
              ("mispicks" for "miss picks", "let rep know" for "let me know")
  partial     about half of the key's words are there
  different   little in common with the key: a different thing was captured

Also lists the cases whose event type or topic status differs between the
run's own repeats (same note, same prompt, a different answer).

--show prints the key's value and the run's value for every "different" one;
those come from the notes, so keep that output on this machine.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

FILLER = set("a an the of to for and or in on at by is are was it that this with our my me i we he she they "
             "rep unknown not stated role title".split())


def tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9$%./-]+", (text or "").lower()):
        w = w.strip("./-")
        if w and w not in FILLER:
            out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


def squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def kind(expected: str, actual: str) -> str:
    """reworded / partial / different, for a value the scorer counted wrong."""
    want, got = tokens(expected), tokens(actual)
    cover = len(want & got) / len(want) if want else 0.0
    # The key's text inside the answer, ignoring spaces and marks ("miss picks" in "mispicks" is not,
    # but the two are nearly the same string), or the two nearly the same overall.
    a, b = squash(expected), squash(actual)
    close = SequenceMatcher(None, a, b).ratio() if a and b else 0.0
    best = max((SequenceMatcher(None, a, b[i:i + len(a)]).ratio() for i in range(0, max(len(b) - len(a), 0) + 1, 3)),
               default=0.0) if a and len(b) >= len(a) else 0.0
    if cover >= 0.7 or close >= 0.8 or best >= 0.85:
        return "reworded"
    return "partial" if cover >= 0.4 or best >= 0.6 else "different"


def main() -> None:
    run = Path(sys.argv[1])
    show = "--show" in sys.argv
    kinds, by_field, strict = Counter(), defaultdict(Counter), [0, 0]
    different = []
    events, statuses = defaultdict(list), defaultdict(list)
    for raw in sorted(run.glob("raw_golden_r*.jsonl")):
        for line in raw.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            s = row.get("score")
            if not s:
                continue
            if s.get("event_type"):
                events[row["id"]].append(s["event_type"]["actual"])
            for t in s.get("topics", []):
                statuses[(row["id"], t["topic"])].append(t["actual"])
            for f in s.get("fields", []):
                if "value_ok" not in f:
                    continue
                strict[1] += 1
                if f["value_ok"]:
                    strict[0] += 1
                    continue
                k = kind(str(f["expected"]), str(f["actual"]))
                kinds[k] += 1
                by_field[f["field"]][k] += 1
                if k == "different":
                    different.append((row["id"], f["field"], f["expected"], f["actual"]))
    right, total = strict
    print(f"Run {run.name}: {right}/{total} values right by the scorer = {100 * right / max(total, 1):.1f}%")
    print(f"  of the {total - right} counted wrong: reworded {kinds['reworded']}, partial {kinds['partial']}, "
          f"different {kinds['different']}")
    lenient = right + kinds["reworded"]
    print(f"  counting reworded as right: {lenient}/{total} = {100 * lenient / max(total, 1):.1f}%")
    print("\n  by field (reworded / partial / different):")
    for fid, c in sorted(by_field.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"    {fid:6s} {c['reworded']:3d} / {c['partial']:3d} / {c['different']:3d}")
    print(f"\n  different, by case: " + "; ".join(f"{cid} {fid}" for cid, fid, _, _ in sorted(set((a, b, "", "") for a, b, _, _ in different))))
    if show:
        for cid, fid, want, got in different:
            print(f"    {cid} {fid}\n        key: {want!r}\n        run: {got!r}")
    wavering = sorted(cid for cid, v in events.items() if len(set(v)) > 1)
    print(f"\n  event type differs between repeats: {len(wavering)} of {len(events)} cases: {', '.join(wavering)}")
    moving = sorted({cid for (cid, _), v in statuses.items() if len(set(v)) > 1})
    print(f"  a topic's status differs between repeats: {len(moving)} cases: {', '.join(moving)}")


if __name__ == "__main__":
    main()
