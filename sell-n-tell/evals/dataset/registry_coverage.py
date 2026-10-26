"""How many real pre-call topics have a registry description -- with the
Campaign Topics names repaired (text.REGISTRY_DAMAGE). Counts only, no text.

    uv run --with pandas --with pyarrow python -m evals.dataset.registry_coverage

The earlier gap profile (profile_gaps.md: 243 titles, 26.3% of mentions)
matched against the damaged names; this recounts with both, side by side.
"""

from __future__ import annotations

from collections import Counter

from evals.dataset.source import load_events, load_registry, make_splitter, topic_index
from evals.dataset.text import title_key


def coverage(events, reg) -> dict:
    index = topic_index(reg)
    split = make_splitter(list(reg["name"]))
    mentions, per_vertical = Counter(), Counter()
    titles, described_titles = set(), set()
    for cell, vertical in zip(events["topics"], events["vertical"], strict=True):
        for t in split(cell):
            hit = index.lookup(t, vertical) is not None
            mentions[hit] += 1
            per_vertical[(vertical, hit)] += 1
            titles.add(title_key(t))
            if hit:
                described_titles.add(title_key(t))
    total = mentions[True] + mentions[False]
    return {"titles": len(titles), "described_titles": len(described_titles),
            "mentions": total, "described_mentions": mentions[True],
            "share": mentions[True] / total if total else 0.0, "per_vertical": per_vertical}


def main() -> None:
    events = load_events()
    for label, repair in (("damaged names (as in profile_gaps.md)", False), ("repaired names", True)):
        c = coverage(events, load_registry(repair=repair))
        print(f"\n## {label}")
        print(f"  distinct titles: {c['titles']:,}   with a description: {c['described_titles']:,}")
        print(f"  mentions with a description: {c['described_mentions']:,} / {c['mentions']:,}  ({c['share']:.1%})")
        for v in sorted({v for v, _ in c["per_vertical"] if isinstance(v, str)}):  # NaN = no vertical
            yes, no = c["per_vertical"][(v, True)], c["per_vertical"][(v, False)]
            print(f"    {v}: {yes / (yes + no):.1%} of {yes + no:,} mentions")


if __name__ == "__main__":
    main()
