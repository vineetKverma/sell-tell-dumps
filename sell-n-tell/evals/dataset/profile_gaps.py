"""Second profiling pass: close the gaps the first report left open.

    uv run --with pandas --with pyxlsb --with openpyxl --with pyarrow \\
        python -m evals.dataset.profile_gaps

Writes ``evals/data/out/profile_gaps.md``. Like the first pass it never prints
note text, objectives or account names. It does print campaign topic titles
and a few truncated topic descriptions, which are internal campaign copy.

The first run parses the .xlsb (minutes) and caches it as parquet under
``evals/data/cache/``; later runs and the sampler load in seconds.

Covers:
  A. topic splitting that keeps comma-containing titles whole; the real match
     rate; how many visits have every topic in the registry (the pool that can
     carry descriptions), per vertical
  B. registry duplicates, non-vertical tags, and what descriptions look like
  C. note quality per vertical: empty, short, mojibake, exact duplicates
  D. plan restatement: notes near-identical to the pre-call objective
  E. candidate pool sizes per vertical for each sampling stratum
  F. personal-data signals per vertical, to size the scrubbing step
"""

from __future__ import annotations

import argparse
import difflib
from collections import Counter
from pathlib import Path

import pandas as pd

from evals.dataset.profile_source import Report
from evals.dataset.source import (
    MOJIBAKE_MARKERS,
    OUT,
    RAW,
    VERTICALS,
    load_events,
    load_registry,
    make_splitter,
)

RESTATEMENT_SAMPLE = 20_000
RESTATEMENT_THRESHOLD = 0.9
SHORT_NOTE_CHARS = 40

# Keyword proxies for the sampling strata -- deliberately loose. They only size
# candidate pools; every sampled record is labelled by hand afterwards.
STRATA = {
    "order placed": r"\b(?:placed (?:an? )?order|ordered|order placed|po #?\d)",
    "quote": r"\bquot(?:e|ed|es|ing)\b",
    "no contact": (
        r"\b(?:not (?:there|in|available)|no one|nobody|unavailable|office (?:was )?closed"
        r"|left (?:a )?(?:flyer|card|catalog|info|voicemail|vm)|no answer)\b"
    ),
    "count with unit": (
        r"\b\d+\s?(?:units?|keys|rooms|beds|trucks|vans|sites|jobs|doors|apts?"
        r"|apartments|buildings|properties|turns)\b"
    ),
    "competitor / price": r"\b(?:competitor|cheaper|price[sd]?|pricing|amazon|lowe'?s|home depot|grainger|ferguson)\b",
    "service issue": r"\b(?:backorder(?:ed)?|back order|mispick|damaged|missing|eta|late delivery|wrong item)\b",
    "next step": r"\b(?:follow(?:ing)? up|f/?u|next (?:week|visit|month)|will (?:send|call|email)|call back)\b",
}
PII = {
    "email": r"[\w.+-]+@[\w-]+\.[\w.]+",
    "phone": r"\b\d{3}[-.\s)]\s?\d{3}[-.\s]\d{4}\b",
    "long number (PO/invoice/quote)": r"\b\d{6,}\b",
}
HEALTHCARE_PERSON = r"\b(?:patient|resident|mr\.|mrs\.|ms\.)\b"


def _pct(n: int, d: int) -> str:
    return f"{n:>9,} / {d:<9,} ({n / max(d, 1):6.1%})"


def topics_section(r: Report, ev: pd.DataFrame, reg: pd.DataFrame, split) -> None:
    r.h("A. Topics, split with registry titles kept whole")
    names = set(reg["name"].dropna())
    comma_names = sorted(n for n in names if "," in n)
    r(f"  registry titles containing a comma ({len(comma_names)}):")
    for n in comma_names:
        r(f"    {n}")

    per_row = ev["topics"].map(split)
    counts = Counter(t for ts in per_row for t in ts)
    total = sum(counts.values())
    matched = sum(n for t, n in counts.items() if t in names)
    r(f"\n  distinct titles after fixed split: {len(counts):,}")
    r(f"  distinct titles in registry:        {sum(t in names for t in counts):,}")
    r(f"  mentions in registry:               {_pct(matched, total)}")
    sizes = Counter(map(len, per_row))
    r(f"  topics per visit (full): {dict(sorted(sizes.items()))}")

    in_reg = per_row.map(lambda ts: [t in names for t in ts])
    ev = ev.assign(
        all_in=in_reg.map(lambda f: bool(f) and all(f)),
        any_in=in_reg.map(any),
        has_note=ev["note"].fillna("").str.strip().str.len() > 0,
    )
    r("\n  visits with a note, by how many of their topics have a description:")
    r(f"    {'vertical':<9}{'all topics':>12}{'some':>12}{'none':>12}")
    for v in (*VERTICALS, None):
        sub = ev[(ev["vertical"] == v) if v else ev["vertical"].isna()]
        sub = sub[sub["has_note"]]
        some = int((sub["any_in"] & ~sub["all_in"]).sum())
        r(f"    {v or '(none)':<9}{int(sub['all_in'].sum()):>12,}{some:>12,}"
          f"{int((~sub['any_in']).sum()):>12,}")

    r("\n  most common titles NOT in the registry, per vertical (top 5):")
    for v in VERTICALS:
        c = Counter(
            t for ts in per_row[ev["vertical"] == v] for t in ts if t not in names
        )
        r(f"    {v}: " + " | ".join(f"{t} ({n:,})" for t, n in c.most_common(5)))


def registry_section(r: Report, reg: pd.DataFrame) -> None:
    r.h("B. Campaign Topics registry")
    dup = reg[reg["name"].duplicated(keep=False)].groupby("name")
    same_desc = sum(g["description"].nunique(dropna=False) == 1 for _, g in dup)
    same_ind = sum(g["industry"].nunique(dropna=False) == 1 for _, g in dup)
    r(f"  duplicated titles: {dup.ngroups}   identical description: {same_desc}   "
      f"identical industry: {same_ind}")
    for name, g in list(dup)[:15]:
        r(f"    x{len(g)}  {name}   industries={sorted(g['industry'].fillna('nan').unique())}")

    tags = reg["industry"].fillna("nan")
    non_vertical = reg[~tags.str.contains(r"\b(?:MH|HS|HL|IS|TR|IN) - ", regex=True)]
    r(f"\n  rows with no vertical tag (MKTG, PI-only, blank): {len(non_vertical)}")
    for name in non_vertical["name"].head(12):
        r(f"    {name}")

    desc = reg["description"].fillna("")
    line_breaks = desc.str.contains("\n", regex=False).mean()
    prices = desc.str.contains(r"[$]\d", regex=True).mean()
    bullet = chr(0x2022)  # kept out of the source text; see source.MOJIBAKE_MARKERS
    bullets = desc.str.contains(r"(?m)^\s*(?:[-*" + bullet + r"]|\d+[.)])", regex=True).mean()
    r("\n  description shape:")
    r(f"    has line breaks:  {line_breaks:.0%}")
    r(f"    has a $ price:    {prices:.0%}")
    r(f"    has bullets/dash: {bullets:.0%}")
    r("\n  three descriptions (first 400 chars):")
    for _, row in reg.dropna(subset=["description"]).sample(3, random_state=1).iterrows():
        text = " ".join(row["description"].split())[:400]
        r(f"\n    [{row['industry']}] {row['name']}\n      {text}")


def notes_section(r: Report, ev: pd.DataFrame) -> None:
    r.h("C. Note quality per vertical")
    note = ev["note"].fillna("")
    stripped = note.str.strip()
    ev = ev.assign(
        empty=stripped.str.len() == 0,
        short=(stripped.str.len() > 0) & (stripped.str.len() < SHORT_NOTE_CHARS),
        mojibake=note.map(lambda s: any(m in s for m in MOJIBAKE_MARKERS)),
        cr=note.str.contains("\r", regex=False) | note.str.contains("_x000D_", regex=False),
        dup=stripped.duplicated(keep=False) & (stripped.str.len() > 0),
    )
    r(f"    {'vertical':<9}{'visits':>9}{'empty':>8}{'short':>8}{'mojibake':>10}{'CR':>7}{'repeated':>10}")
    for v in VERTICALS:
        s = ev[ev["vertical"] == v]
        r(f"    {v:<9}{len(s):>9,}{s['empty'].mean():>8.1%}{s['short'].mean():>8.1%}"
          f"{s['mojibake'].mean():>10.1%}{s['cr'].mean():>7.1%}{s['dup'].mean():>10.1%}")
    reps = stripped[stripped.str.len() > 0].value_counts()
    r(f"\n  distinct non-empty notes: {len(reps):,}; notes written more than once: "
      f"{int((reps > 1).sum()):,}; the most repeated appears {int(reps.iloc[0]):,} times "
      f"(length {len(reps.index[0])} chars)")


def objective_section(r: Report, ev: pd.DataFrame) -> None:
    r.h("D. Plan restatement (note near-identical to the pre-call objective)")
    obj = ev["objective"].fillna("").str.strip()
    lengths = obj[obj.str.len() > 0].str.len()
    r(f"  objective empty: {(obj.str.len() == 0).mean():.1%}   "
      f"length p50 / p90: {lengths.median():.0f} / {lengths.quantile(0.9):.0f}")
    r(f"  objective identical to the topics cell: {(obj == ev['topics'].fillna('').str.strip()).mean():.1%}")

    both = ev[(obj.str.len() > 0) & (ev["note"].fillna("").str.strip().str.len() > 0)]
    sample = both.sample(min(RESTATEMENT_SAMPLE, len(both)), random_state=0)
    ratio = [
        difflib.SequenceMatcher(None, str(a).strip().lower(), str(b).strip().lower()).ratio()
        for a, b in zip(sample["objective"], sample["note"], strict=True)
    ]
    sample = sample.assign(ratio=ratio)
    r(f"  sample of {len(sample):,} visits with both fields:")
    r(f"    {'vertical':<9}{'identical':>11}{'>= 0.9 similar':>16}")
    for v in VERTICALS:
        s = sample[sample["vertical"] == v]
        if len(s):
            r(f"    {v:<9}{(s['ratio'] == 1).mean():>11.1%}"
              f"{(s['ratio'] >= RESTATEMENT_THRESHOLD).mean():>16.1%}   (n={len(s):,})")


def strata_section(r: Report, ev: pd.DataFrame) -> None:
    r.h("E. Candidate pool sizes per stratum (keyword proxies, notes with text)")
    ev = ev[ev["note"].fillna("").str.strip().str.len() > 0]
    note = ev["note"].str.lower()
    flags = {name: note.str.contains(rx, regex=True) for name, rx in STRATA.items()}
    flags["short (< 40 chars)"] = ev["note"].str.strip().str.len() < SHORT_NOTE_CHARS
    header = "".join(f"{v:>10}" for v in VERTICALS)
    r(f"    {'stratum':<22}{header}")
    for name, f in flags.items():
        row = "".join(f"{int(f[ev['vertical'] == v].sum()):>10,}" for v in VERTICALS)
        r(f"    {name:<22}{row}")
    r("  (counts, not rates -- the question is whether each cell can supply "
      "a few records)")


def pii_section(r: Report, ev: pd.DataFrame) -> None:
    r.h("F. Personal-data signals per vertical (rate of notes)")
    ev = ev[ev["note"].fillna("").str.strip().str.len() > 0]
    note = ev["note"]
    header = "".join(f"{v:>9}" for v in VERTICALS)
    r(f"    {'signal':<32}{header}")
    for name, rx in PII.items():
        f = note.str.contains(rx, regex=True)
        r(f"    {name:<32}" + "".join(f"{f[ev['vertical'] == v].mean():>9.1%}" for v in VERTICALS))
    hl = note[ev["vertical"] == "HL"].str.lower()
    r(f"\n  HL notes mentioning a patient/resident/title: "
      f"{hl.str.contains(HEALTHCARE_PERSON, regex=True).mean():.1%}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Second profiling pass for AIML-2898.")
    ap.add_argument("--raw", type=Path, default=RAW, help="folder holding the source files")
    ap.add_argument("--out", type=Path, default=OUT / "profile_gaps.md")
    args = ap.parse_args()

    r = Report()
    r("# AIML-2898 source profile -- gap pass")
    ev = load_events(args.raw)
    reg = load_registry(args.raw)
    split = make_splitter(set(reg["name"].dropna()))
    r(f"\nevents: {len(ev):,} rows   registry: {len(reg):,} rows")
    r(f"vertical mapped: {ev['vertical'].notna().mean():.3%} "
      f"(unmapped values: {sorted(ev.loc[ev['vertical'].isna(), 'industry'].fillna('nan').unique())})")

    for section in (
        lambda: topics_section(r, ev, reg, split),
        lambda: registry_section(r, reg),
        lambda: notes_section(r, ev),
        lambda: objective_section(r, ev),
        lambda: strata_section(r, ev),
        lambda: pii_section(r, ev),
    ):
        try:
            section()
        except Exception as exc:
            r(f"\n    SECTION FAILED -- {type(exc).__name__}: {exc}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(r.lines) + "\n", encoding="utf-8")
    print(f"\nReport written to {args.out}")


if __name__ == "__main__":
    main()
