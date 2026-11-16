"""Where two extract_eval runs differ, case by case -- read-only, ids and field
ids only, no note text, no model calls.

    cd <repo>
    uv run python C:\\tmp\\run_diff.py evals\\runs\\extract-<old> evals\\runs\\extract-<new>

For each run, over every repeat of the golden set: how often each case's event
type is right, and how often each filled field's value agrees with the key
(fields the key scores as captured). Prints only the cases and fields whose
count of right answers differs between the runs, with the expected and the two
runs' answers for event type (labels only).

With --show=U-09,U-07 (field ids) it also prints, for those fields' changed cases,
the key's value and each run's values -- these are taken from the notes, so
keep that output on this machine.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path


def load(run: Path):
    event, values, got = defaultdict(list), defaultdict(list), defaultdict(list)
    want, texts, keys = {}, defaultdict(list), {}
    for raw in sorted(run.glob("raw_golden_r*.jsonl")):
        for line in raw.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            s = row.get("score")
            if not s:
                continue
            e = s.get("event_type")
            if e:
                event[row["id"]].append(bool(e["ok"]))
                got[row["id"]].append(e["actual"])
                want[row["id"]] = e["expected"]
            for f in s.get("fields", []):
                if "value_ok" in f:
                    values[(row["id"], f["field"])].append(bool(f["value_ok"]))
                if f.get("expected") not in (None, ""):
                    texts[(row["id"], f["field"])].append(f.get("actual"))
                    keys[(row["id"], f["field"])] = f["expected"]
    return event, values, got, want, texts, keys


def main() -> None:
    old, new = Path(sys.argv[1]), Path(sys.argv[2])
    show = next((a.split("=", 1)[1].split(",") for a in sys.argv[3:] if a.startswith("--show=")), [])
    (e_old, v_old, g_old, want, t_old, keys), (e_new, v_new, g_new, _, t_new, _) = load(old), load(new)
    print(f"old {old.name} | new {new.name}\n")
    print("Event type, right over the repeats:")
    for cid in sorted(set(e_old) | set(e_new)):
        a, b = sum(e_old.get(cid, [])), sum(e_new.get(cid, []))
        if a != b:
            print(f"  {cid}: old {a}/{len(e_old.get(cid, []))} new {b}/{len(e_new.get(cid, []))} | "
                  f"key {want.get(cid)} | old {g_old.get(cid)} | new {g_new.get(cid)}")
    print(f"  total right: old {sum(map(sum, e_old.values()))}/{sum(map(len, e_old.values()))}, "
          f"new {sum(map(sum, e_new.values()))}/{sum(map(len, e_new.values()))}")
    print("\nField values that agree with the key, over the repeats (captured fields only):")
    for key in sorted(set(v_old) | set(v_new)):
        a, b = v_old.get(key, []), v_new.get(key, [])
        if sum(a) != sum(b) or len(a) != len(b):
            print(f"  {key[0]} {key[1]}: old {sum(a)}/{len(a)} new {sum(b)}/{len(b)}")
            if key[1] in show:
                print(f"      key: {keys.get(key)!r}")
                print(f"      old: {t_old.get(key)!r}")
                print(f"      new: {t_new.get(key)!r}")
    print(f"  total agreeing: old {sum(map(sum, v_old.values()))}/{sum(map(len, v_old.values()))}, "
          f"new {sum(map(sum, v_new.values()))}/{sum(map(len, v_new.values()))}")


if __name__ == "__main__":
    main()
