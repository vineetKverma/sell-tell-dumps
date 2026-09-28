"""Draw the golden-set sample from the events export (AIML-2898, step 1).

    uv run --with pandas --with pyxlsb --with openpyxl --with pyarrow \\
        python -m evals.dataset.sample --per-vertical 2 --name pilot

Writes two files to ``evals/data/out/``:

- ``sample_<name>.jsonl`` -- the sampled records, including the (cleaned,
  masked) note text. Customer data: it stays on the machine that has the
  source file.
- ``sample_<name>_summary.md`` -- counts only, safe to share.

How records are chosen, per vertical:

1. Only visits with a non-empty note, a known vertical, and -- by default --
   a registry description for every planned topic (the agent is meant to get
   descriptions at call time, so the test cases should carry them).
2. Exact-duplicate notes are dropped; healthcare notes naming a patient or
   resident are dropped (the Method tab: never capture patient details).
3. Strata are taken in turn, one record each, so even a small sample spreads
   across outcomes. The starting stratum rotates by vertical, so a 2-per-
   vertical pilot still covers most strata overall. Anything left is random.
"""

from __future__ import annotations

import argparse
import difflib
import json
import random
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from evals.dataset.source import (
    OUT,
    RAW,
    load_events,
    load_registry,
    topic_index,
)
from evals.dataset.text import (
    HEALTHCARE_PERSON,
    STRATA,
    VERTICALS,
    clean_note,
    damage_count,
    make_splitter,
    mask_pii,
    short_description,
    strata_for,
)

# The Method tab calls plan restatement "the most likely failure mode for an
# automated agent" and asks for an explicit test, so it is a stratum too.
RESTATEMENT = "plan restatement"
RESTATEMENT_THRESHOLD = 0.9
# Restatement needs a pairwise similarity, which is slow over 400k rows; it is
# computed on this many random candidates per vertical.
RESTATEMENT_SCAN = 4_000
STRATUM_ORDER = [*STRATA, "short", RESTATEMENT]
PLACEHOLDER_CAMPAIGN = "standard_sales"  # not in the source; the agent ignores it today


def _similar(a: str, b: str) -> bool:
    a, b = " ".join(a.lower().split()), " ".join(b.lower().split())
    return bool(a) and difflib.SequenceMatcher(None, a, b).ratio() >= RESTATEMENT_THRESHOLD


def build_pool(ev: pd.DataFrame, reg: pd.DataFrame, require_descriptions: bool, seed: int):
    index = topic_index(reg)
    split = make_splitter(index.titles)

    df = ev[ev["vertical"].notna()].copy()
    df["note_clean"] = df["note"].map(clean_note)
    df = df[df["note_clean"].str.len() > 0]
    df = df[~df["note_clean"].str.lower().duplicated()]
    is_patient = (df["vertical"] == "HL") & df["note_clean"].str.lower().str.contains(
        HEALTHCARE_PERSON, regex=True
    )
    df = df[~is_patient]

    df["topic_list"] = df["topics"].map(split)
    df["resolved"] = [
        [index.lookup(t, v) for t in ts]
        for ts, v in zip(df["topic_list"], df["vertical"], strict=True)
    ]
    df["all_described"] = df["resolved"].map(lambda rs: bool(rs) and all(rs))
    if require_descriptions:
        df = df[df["all_described"]]

    df["strata"] = df["note_clean"].map(strata_for)
    rng = random.Random(seed)
    restated: set = set()
    for v in VERTICALS:
        ids = list(df.index[df["vertical"] == v])
        for i in rng.sample(ids, min(RESTATEMENT_SCAN, len(ids))):
            if _similar(str(df.at[i, "objective"] or ""), df.at[i, "note_clean"]):
                restated.add(i)
    df["strata"] = [
        [*s, RESTATEMENT] if i in restated else s
        for i, s in zip(df.index, df["strata"], strict=True)
    ]
    return df, index


def draw(pool: pd.DataFrame, per_vertical: int, seed: int) -> list[tuple[int, str]]:
    """(row index, stratum it was picked for) per chosen record."""
    rng = random.Random(seed)
    picked: list[tuple[int, str]] = []
    for offset, v in enumerate(VERTICALS):
        sub = pool[pool["vertical"] == v]
        order = STRATUM_ORDER[offset % len(STRATUM_ORDER) :] + STRATUM_ORDER[: offset % len(STRATUM_ORDER)]
        taken: set = set()
        for stratum in order:
            if len(taken) >= per_vertical:
                break
            candidates = [i for i in sub.index[sub["strata"].map(lambda s, st=stratum: st in s)] if i not in taken]
            if candidates:
                i = rng.choice(candidates)
                taken.add(i)
                picked.append((i, stratum))
        rest = [i for i in sub.index if i not in taken]
        for i in rng.sample(rest, min(per_vertical - len(taken), len(rest))):
            taken.add(i)
            picked.append((i, "random"))
    return picked


def to_record(row: pd.Series, n: int, picked_for: str) -> dict:
    topics = []
    for title, hit in zip(row["topic_list"], row["resolved"], strict=True):
        topics.append(
            {
                "title": title,
                "description": hit.description if hit else "",
                "description_short": short_description(hit.description) if hit else "",
                "registry_industry": hit.industry if hit else "",
            }
        )
    return {
        "id": f"{row['vertical']}-{n:03d}",
        "vertical": row["vertical"],
        "industry": row["industry"],
        "campaign_type": PLACEHOLDER_CAMPAIGN,
        "topics": topics,
        "note": mask_pii(row["note_clean"]),
        "objective": mask_pii(clean_note(row["objective"])),
        "strata": row["strata"],
        "picked_for": picked_for,
        "source_row": int(row.name),
    }


def summary(ev, reg_raw, reg, pool, records, name: str) -> list[str]:  # noqa: PLR0917
    lines = [f"# Sample '{name}' -- summary (counts only)", ""]
    lines.append("## Registry repair")
    before = damage_count(list(reg_raw["name"]) + list(reg_raw["description"]))
    after = damage_count(list(reg["name"]) + list(reg["description"]))
    lines.append("  vertical text inside names/descriptions (before -> after repair):")
    for token in before:
        lines.append(f"    {before[token]:>5} -> {after[token]:<5} {token}")

    def match_rate(r):
        idx = topic_index(r)
        split = make_splitter(idx.titles)
        titles = [t for cell in ev["topics"] for t in split(cell)]
        hits = sum(idx.lookup(t, None) is not None for t in titles)
        return hits, len(titles)

    for label, r in (("before repair", reg_raw), ("after repair", reg)):
        hits, total = match_rate(r)
        lines.append(f"  topic mentions found in registry, {label}: {hits:,} / {total:,} ({hits / max(total, 1):.1%})")

    lines += ["", "## Candidate pool after filters, per stratum"]
    header = "".join(f"{v:>9}" for v in VERTICALS)
    lines.append(f"    {'stratum':<22}{header}")
    lines.append(f"    {'(all)':<22}" + "".join(f"{int((pool['vertical'] == v).sum()):>9,}" for v in VERTICALS))
    for stratum in STRATUM_ORDER:
        has = pool["strata"].map(lambda s, st=stratum: st in s)
        lines.append(f"    {stratum:<22}" + "".join(f"{int((has & (pool['vertical'] == v)).sum()):>9,}" for v in VERTICALS))

    lines += ["", f"## Drawn: {len(records)} records"]
    by = Counter((r["vertical"], r["picked_for"]) for r in records)
    for (v, s), n in sorted(by.items()):
        lines.append(f"    {v}  {s:<22} {n}")
    lengths = [len(r["note"]) for r in records]
    if lengths:
        lines.append(f"  note length min / median / max: {min(lengths)} / {sorted(lengths)[len(lengths) // 2]} / {max(lengths)}")
    lines.append(f"  topics per record: {dict(Counter(len(r['topics']) for r in records))}")
    masked = sum(bool(re.search(r"\[(?:EMAIL|PHONE|NUMBER)\]", r["note"])) for r in records)
    lines.append(f"  records with masked email/phone/number: {masked}")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description="Draw the AIML-2898 golden-set sample.")
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--name", default="pilot")
    ap.add_argument("--per-vertical", type=int, default=2)
    ap.add_argument("--seed", type=int, default=2898)
    ap.add_argument(
        "--allow-undescribed",
        action="store_true",
        help="also sample visits whose topics have no registry description",
    )
    args = ap.parse_args()

    ev = load_events(args.raw)
    reg_raw = load_registry(args.raw, repair=False)
    reg = load_registry(args.raw)
    pool, _ = build_pool(ev, reg, not args.allow_undescribed, args.seed)
    picked = draw(pool, args.per_vertical, args.seed)
    counters: Counter = Counter()
    records = []
    for i, stratum in picked:
        v = pool.at[i, "vertical"]
        counters[v] += 1
        records.append(to_record(pool.loc[i], counters[v], stratum))

    args.out.mkdir(parents=True, exist_ok=True)
    data_path = args.out / f"sample_{args.name}.jsonl"
    with data_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    lines = summary(ev, reg_raw, reg, pool, records, args.name)
    summary_path = args.out / f"sample_{args.name}_summary.md"
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nRecords (contain note text, keep on this machine): {data_path}")
    print(f"Summary (safe to share):                          {summary_path}")


if __name__ == "__main__":
    main()
