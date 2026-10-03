"""Synthetic dictations for fields no real note states (AIML-2898 top-up).

Three rounds searched the export for HS-08 (PTAC and filter population) and
HS-09 (engineering shop stock gaps). Hundreds of notes mention filters, PTACs
or the shop, but none that was labelled states the unit count, the PM
schedule, or what the shop is missing (see scan_missing_summary.md and the
finalize_topup_v*.md summaries). So these fields get written cases.

The notes below are invented -- no customer, property or person is real --
and every record is marked ``synthetic: true`` with ids prefixed ``S-``. The
planned topics are real Campaign Topics titles for the vertical, resolved
against the registry the same way real records are, so the agent sees the
same kind of input. The expected answers are NOT written by hand: the records
go through the same two-build labelling as the real notes, and finalize
``--keep-target-stated 3`` keeps a record only if both builds agree its target
field is stated.

    uv run --with pandas --with pyxlsb --with openpyxl --with pyarrow \\
        python -m evals.dataset.build --name synth_a --sampler synthetic --fresh
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evals.dataset.sample import PLACEHOLDER_CAMPAIGN
from evals.dataset.source import OUT, RAW, load_registry, topic_index
from evals.dataset.text import VERTICAL_TOKENS, mask_pii, short_description

PTACS = "HS Q3 2026 HVAC PTACs"
MSP = "HS Q3 2026 Maintenance Savings Program (MSP)"
PLUMBING = "HS SEP 2026 Everyday Essentials - PLUMBING"

# (target field, vertical, planned topics, note)
CASES: list[tuple[str, str, list[str], str]] = [
    ("HS-08", "HS", [PTACS],
     "Met with Ray, the chief engineer, on site. They have 186 PTAC units in the building and "
     "change the filters every 90 days. Next PM round is the first week of next month. He wants "
     "pricing on 200 filters and two spare PTACs before then."),
    ("HS-08", "HS", [PTACS, MSP],
     "Phone call with the director of engineering. 240 rooms, all on PTACs, about a dozen past "
     "end of life. They do PM twice a year, spring and fall, and they're short on filters for the "
     "fall round. Sending a quote for 250 filters under the maintenance savings program."),
    ("HS-08", "HS", [PTACS],
     "Stopped by the property and met Tom, the maintenance lead. 120 PTACs, filters cleaned "
     "monthly and replaced quarterly. Not replacing any units this year, the budget is frozen "
     "until January."),
    ("HS-09", "HS", [MSP],
     "Walked the engineering shop with Luis. They're stocked to maybe 70 percent of the program "
     "list. Missing ballasts, toilet flappers and GFCI outlets, and they're out of the 2-foot LED "
     "tubes. He'll send me the full list and I'll quote it under the maintenance savings program."),
    ("HS-09", "HS", [PLUMBING],
     "Met with the chief engineer. The shop is stocked to the program list except plumbing: no "
     "cartridges for the shower valves and only two flush valves left. Placed an order for both "
     "today."),
    ("HS-09", "HS", [MSP],
     "Phone call with the engineering manager. Shop stock fell off after the last manager left, "
     "no spare door closers, no thermostats, and nothing on the program list for pool chemicals. "
     "Wants to sit down next week to rebuild the stock against the program list."),
]

def industry_of(vertical: str) -> str:
    for token in VERTICAL_TOKENS:
        if token.startswith(vertical + " "):
            return token
    return vertical


def records(index) -> list[dict]:
    out, missing = [], []
    for n, (fid, vertical, titles, note) in enumerate(CASES, 1):
        topics = []
        for title in titles:
            hit = index.lookup(title, vertical)
            if hit is None:
                missing.append(title)
                continue
            topics.append({"title": title, "description": hit.description,
                           "description_short": short_description(hit.description),
                           "registry_industry": hit.industry})
        if mask_pii(note) != note:
            raise SystemExit(f"S-{vertical}-{n:03d}: note contains something mask_pii would hide")
        out.append({
            "id": f"S-{vertical}-{n:03d}", "vertical": vertical, "industry": industry_of(vertical),
            "campaign_type": PLACEHOLDER_CAMPAIGN, "topics": topics, "note": note, "objective": "",
            "strata": ["synthetic"], "picked_for": f"field:{fid}", "source_row": -n,
            "synthetic": True,
        })
    if missing:
        raise SystemExit(f"topic titles not in the registry: {sorted(set(missing))}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Write the synthetic sample.")
    ap.add_argument("--raw", type=Path, default=RAW)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--name", default="synth")
    ap.add_argument("--per-vertical", type=int, help=argparse.SUPPRESS)  # passed by build.py; unused
    args = ap.parse_args()
    recs = records(topic_index(load_registry(args.raw)))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"sample_{args.name}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    (args.out / f"sample_{args.name}_summary.md").write_text(
        f"# Synthetic sample '{args.name}'\n\n{len(recs)} invented dictations: "
        + ", ".join(f"{r['id']} ({r['picked_for']})" for r in recs) + "\n", encoding="utf-8")
    print(f"{len(recs)} synthetic records -> {path}")


if __name__ == "__main__":
    main()
