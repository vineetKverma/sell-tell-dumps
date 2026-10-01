"""Draw a field-targeted top-up sample (AIML-2898 follow-up).

golden_v1 was stratified by outcome (orders, quotes, no contact, ...), so the
rarer vertical fields -- mentioned in ~0.2-8% of notes per the Evidence Base
tab of must-capture-fields.xlsx -- never came up in its 15 notes per vertical:
33 of the 54 vertical fields have no stated example, and the eval can only
check the agent does not invent them.

This picks, for each of those fields, a few notes FROM THAT FIELD'S VERTICAL
whose text matches a keyword pattern for the field. A keyword match is only a
candidate: "HVAC" does not state a repair-vs-replace posture. The candidates
then go through the same two-build labelling as golden_v1, and finalize
``--keep-target-stated`` keeps only the notes where both builds agree the
target field is stated.

    uv run --group dataset python -m evals.dataset.build --name topup_a \\
        --sampler topup ...        (see build.py; same seed -> same notes)

Writes ``sample_<name>.jsonl`` in the same format as sample.py, with
``picked_for`` set to ``field:<ID>`` and ids prefixed ``T-`` so they never
collide with golden_v1.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

from evals.dataset.sample import build_pool, to_record
from evals.dataset.source import OUT, RAW, load_events, load_registry

# Field id -> candidate pattern (case-insensitive). Where the Evidence Base tab
# names what it measured, the pattern follows it; the rest are written from the
# field definition. Broad on purpose: labelling, not the pattern, decides.
TARGETS: dict[str, str] = {
    "HL-01": r"\bdssi\b|\bgpo\b|punch ?out|premier|vizient|healthtrust|e-?procurement|\bportal\b",
    "HL-03": r"\b\d+\s*[- ]?beds?\b|\bcensus\b|skilled nursing|\bsnf\b|assisted living|memory care|long[- ]term care",
    "HL-05": r"\d+(\.\d+)?\s*(\"|''|in\.?\b|inch(es)?\b|ft\.?\b|feet\b|foot\b|cu\.? ?ft)|\b\d+\s*x\s*\d+\b",
    "HL-06": r"\bsamples?\b|\btrial\b|\bdemo(ed|nstrat\w*)?\b",
    "HL-07": r"hurricane|\bstorms?\b|emergency (prep\w*|suppl\w*|kit)|disaster|\bgenerators?\b",
    "HL-08": r"\bdispensers?\b",
    "HL-09": r"no (current )?need|(don'?t|do not|doesn'?t|does not) need|all set|fully stocked|nothing (needed|at this time)",
    "HS-03": r"\blinens?\b|\bterry\b|\btowels?\b|\bsheets\b|bedding|\bpars?\b|amenit",
    "HS-07": r"\bproperties\b|portfolio|sister (hotel|propert)|multiple (sites|hotels|locations|properties)",
    "HS-08": r"\bptacs?\b|\bfilters?\b",
    "HS-09": r"chief engineer|engineering (shop|dept|department)|shop stock|maintenance shop|\bshop\b.{0,40}\b(stock|parts)\b",
    "IN-04": r"no (current )?need|(don'?t|do not|doesn'?t|does not) need|not interested|nothing (needed|at this time)|all set",
    "IN-05": r"chemicals?|janitorial|cleaning (suppl\w*|products?|chem\w*)|ecolab|diversey|spartan",
    "IN-06": r"(vendor|manufacturer|mfg|factory) (rep|specialist)|specialist|bring (in|out) (a |the |our )?(rep|specialist)",
    "IN-07": r"\blocations\b|multiple (sites|campuses|buildings|plants)|other (sites|locations|plants|campus\w*)",
    "IN-08": r"invoic|\bbilling\b|credit memo|\bstatements?\b",
    "IS-02": r"\bbids?\b|\brfp\b|\brfq\b|approv|threshold|purchase orders?|\bboard\b",
    "IS-03": r"contract|co-?op\b|cooperative|omnia|sourcewell|\btips\b|buyboard|\bgsa\b",
    "IS-05": r"\bdistrict\b|all (of )?(the |their )?(sites|schools|properties|locations)|multiple (sites|schools|locations|properties)",
    "IS-06": r"\bhud\b|nspire|\breac\b|inspections?",
    "IS-07": r"make[- ]?readys?|\bturns?\b|vacan|move[- ]?outs?",
    "IS-09": r"\bbadges?\b|escort|background check|gate code|check[- ]in|security",
    "MH-01": r"make[- ]?readys?|\bturns?\b|vacan|move[- ]?outs?",
    "MH-02": r"(hvac|\bac\b|a/c|condens|compressor|air handler|\bcoils?\b|furnace|refrigerant).{0,80}(replac|repair|\bfix)"
             r"|(replac|repair).{0,80}(hvac|condens|compressor|air handler|furnace)",
    "MH-03": r"in[- ]house|subcontract|contractors?|\binstall\w*",
    "MH-04": r"cheaper|price match|beat (the|their|our) price|lower price|competitor|home depot|lowe'?s|amazon|grainger|ferguson",
    "MH-06": r"water heaters?",
    "MH-08": r"\bpools?\b|seasonal|landscap|\bgrounds\b|\bsnow\b|ice melt",
    "MH-09": r"credit (hold|limit|app\w*)|on hold|past due|purchase orders?|\bpo\b|collections|account (is )?(on hold|blocked)",
    "TR-02": r"(\$\s?\d|\d+\s?%).{0,60}(cheaper|less|lower|competitor|home depot|lowe'?s|ferguson)"
             r"|(cheaper|lower|less).{0,60}(\$\s?\d|\d+\s?%)",
    "TR-04": r"inventory|stock(ing)? (program|list)|van stock|truck stock|stock up",
    "TR-06": r"\bjobs?\b|job ?sites?|\bprojects?\b",
    "TR-09": r"homeowners?|their customers?|end (customer|user)s?|\bclients?\b",
}
PATTERNS = {fid: re.compile(p, re.IGNORECASE) for fid, p in TARGETS.items()}


def vertical_of(field_id: str) -> str:
    return field_id.split("-")[0]


def draw_targets(pool, per_field: int, seed: int, exclude_rows: set[int],
                 fields: list[str] | None = None) -> list[tuple[int, str]]:
    """(row index, 'field:<ID>') for up to ``per_field`` candidates per field,
    each note used once, notes already in golden_v1 skipped. ``fields``
    limits the draw to those field ids (a second round)."""
    rng = random.Random(seed)
    used: set[int] = set(exclude_rows)
    picked: list[tuple[int, str]] = []
    for fid, rx in PATTERNS.items():
        if fields and fid not in fields:
            continue
        sub = pool[pool["vertical"] == vertical_of(fid)]
        hits = [i for i, text in zip(sub.index, sub["note_clean"], strict=True)
                if int(i) not in used and rx.search(text)]
        for i in rng.sample(hits, min(per_field, len(hits))):
            used.add(int(i))
            picked.append((i, f"field:{fid}"))
    return picked


def golden_source_rows(out: Path, also: list[str] = ()) -> set[int]:
    """Source rows already used: every frozen golden set, plus the samples of
    the runs named in ``also`` (a later round skips notes an earlier round
    already labelled, kept or not)."""
    rows: set[int] = set()
    paths = [*out.glob("golden_*.jsonl"), *(out / f"sample_{n}.jsonl" for n in also)]
    for path in paths:
        if not path.exists():
            raise SystemExit(f"{path.name} not found -- check the --skip-samples names")
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.add(int(json.loads(line)["source_row"]))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description="Draw the field-targeted top-up sample.")
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--name", default="topup")
    ap.add_argument("--per-field", type=int, default=6)
    ap.add_argument("--seed", type=int, default=2898)
    ap.add_argument("--fields", help="comma-separated field ids to draw for (default: all 33)")
    ap.add_argument("--skip-samples", help="comma-separated earlier run names whose notes to skip, e.g. topup_a")
    ap.add_argument("--id-prefix", default="T-", help="e.g. T2- for a second round, so ids never collide")
    ap.add_argument("--per-vertical", type=int, help=argparse.SUPPRESS)  # passed by build.py; unused
    args = ap.parse_args()

    fields = [f.strip() for f in (args.fields or "").split(",") if f.strip()]
    unknown = sorted(set(fields) - set(PATTERNS))
    if unknown:
        raise SystemExit(f"no pattern for {unknown}; known: {', '.join(PATTERNS)}")
    skip = [s.strip() for s in (args.skip_samples or "").split(",") if s.strip()]
    if args.name in skip:
        raise SystemExit("--skip-samples must not name this run itself")

    ev = load_events(args.raw)
    pool, _ = build_pool(ev, load_registry(args.raw), True, args.seed)
    exclude = golden_source_rows(args.out, skip)
    picked = draw_targets(pool, args.per_field, args.seed, exclude, fields or None)

    counters: Counter = Counter()
    records = []
    for i, why in picked:
        v = pool.at[i, "vertical"]
        counters[v] += 1
        rec = to_record(pool.loc[i], counters[v], why)
        rec["id"] = args.id_prefix + rec["id"]
        records.append(rec)

    args.out.mkdir(parents=True, exist_ok=True)
    data_path = args.out / f"sample_{args.name}.jsonl"
    data_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")

    found = Counter(why for _, why in picked)
    lines = [f"# Top-up sample '{args.name}' (counts only)", "",
             f"excluded (already in a golden set): {len(exclude)} notes",
             f"candidates drawn: {len(records)}  (up to {args.per_field} per field)", "",
             "    field   pool matches  drawn"]
    for fid, rx in PATTERNS.items():
        if fields and fid not in fields:
            continue
        n = int(pool[pool["vertical"] == vertical_of(fid)]["note_clean"].map(lambda t, r=rx: bool(r.search(t))).sum())
        lines.append(f"    {fid:<7} {n:>12,}  {found[f'field:{fid}']:>5}")
    (args.out / f"sample_{args.name}_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    print(f"\nRecords (contain note text, keep on this machine): {data_path}")


if __name__ == "__main__":
    main()
