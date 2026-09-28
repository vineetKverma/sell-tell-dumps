"""Profile the three source files before anything is sampled or labelled.

One command, one report. Finds the files in ``evals/data/raw/`` by name, reads
each once, and writes ``evals/data/out/profile_report.md`` (also printed). The
report is safe to share: it never contains note text, pre-call objectives or
account names -- only column names, counts, category values and campaign
topic titles.

    uv run --group dataset python -m evals.dataset.profile_source

What it settles for the curation pipeline:

- the real column names and how ``Account.Industry`` spells each vertical
- note lengths and carriage-return artefact rates
- how pre-call topics are delimited, and whether titles match the registry
- how topic-name prefixes ("HC", "MH", ...) line up with ``Industry__c``, and
  whether a visit's account industry agrees with its topics' industry
- any low-cardinality column that might already hold a label (event type,
  outcome, campaign)
- the must-capture workbook's tabs, whether any business decisions have been
  filled in, and the Method & Caveats text
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "evals" / "data" / "raw"
OUT = ROOT / "evals" / "data" / "out"

# Matched case-insensitively and by containment: the real header spelling is
# part of what this script is here to find out.
EVENT_COLUMNS = {
    "industry": "industry",
    "objective": "objective",
    "topics": "selected_pcp_topics",
    "note": "description",
}
# Never printed, whatever their cardinality.
PRIVATE = {"note", "objective"}
# Column-name fragments that suggest a person or account. Excluded from the
# low-cardinality dump even when a small file makes them look categorical.
PRIVATE_HINTS = ("name", "account", "contact", "owner", "email", "phone", "address", "id")
SHORT_NOTE_CHARS = 40
LOW_CARDINALITY = 40
CR_ARTEFACTS = ("_x000D_", "\r")


class Report:
    """Collects lines so the same text goes to stdout and the report file."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def __call__(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def h(self, title: str) -> None:
        self(f"\n## {title}\n")

    def counts(self, series: pd.Series, limit: int = 40) -> None:
        vc = series.value_counts(dropna=False)
        for value, n in vc.head(limit).items():
            self(f"    {n:>9,}  {value}")
        if len(vc) > limit:
            self(f"    ... {len(vc) - limit:,} more values")


def _find(columns: list[str], needle: str) -> str | None:
    norm = {c: c.lower().replace(" ", "_").replace(".", "_") for c in columns}
    hits = [c for c, n in norm.items() if needle in n]
    return hits[0] if hits else None


def _discover(raw: Path, pattern: str) -> Path | None:
    hits = sorted(p for p in raw.glob(pattern) if p.is_file())
    return hits[0] if hits else None


def _engine(path: Path) -> str:
    return "pyxlsb" if path.suffix.lower() == ".xlsb" else "openpyxl"


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".csv":
        for enc in ("utf-8-sig", "cp1252"):
            try:
                return pd.read_csv(path, encoding=enc, dtype=str)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"{path}: neither UTF-8 nor cp1252")
    return pd.read_excel(path, engine=_engine(path), sheet_name=0, dtype=str)


def _split_topics(cell: object) -> list[str]:
    if not isinstance(cell, str):
        return []
    return [t.strip() for t in cell.split(",") if t.strip()]


def _prefix(title: str) -> str:
    parts = title.split(maxsplit=1)
    return parts[0] if parts else ""


def profile_events(r: Report, path: Path) -> pd.DataFrame:  # noqa: PLR0912
    r.h(f"Events: {path.name}")
    if path.suffix.lower() != ".csv":
        r(f"sheets: {pd.ExcelFile(path, engine=_engine(path)).sheet_names}")
    df = _read_table(path)
    r(f"rows: {len(df):,}   columns: {len(df.columns)}")

    cols = {k: _find(list(df.columns), n) for k, n in EVENT_COLUMNS.items()}
    r("\ncolumn  (null %, distinct values)")
    for col in df.columns:
        r(f"    {df[col].isna().mean():6.1%}  {df[col].nunique():>9,}  {col}")
    r("\nresolved:")
    for key, col in cols.items():
        r(f"    {key:<10} -> {col or 'NOT FOUND'}")

    shown_elsewhere = {c for c in cols.values() if c}
    low = [
        c for c in df.columns
        if c not in shown_elsewhere
        and not any(h in c.lower() for h in PRIVATE_HINTS)
        and 1 < df[c].nunique() <= LOW_CARDINALITY
    ]
    if low:
        r.h("Low-cardinality columns (possible labels: event type, outcome, campaign)")
        for c in low:
            r(f"\n  {c}")
            r.counts(df[c])

    if cols["industry"]:
        r.h(f"{cols['industry']} (vertical)")
        r.counts(df[cols["industry"]])
        if cols["note"]:
            has_note = df[cols["note"]].fillna("").str.strip().str.len() > 0
            r("\n  rows with a non-empty note, per value:")
            r.counts(df.loc[has_note, cols["industry"]])

    if cols["note"]:
        notes = df[cols["note"]].dropna()
        notes = notes[notes.str.strip().str.len() > 0]
        lengths = notes.str.len()
        r.h(f"{cols['note']} (post-call note) -- statistics only, no text")
        r(f"  non-empty: {len(notes):,}")
        r(
            "  length p10 / p50 / p90 / p99 / max: "
            f"{lengths.quantile(0.1):.0f} / {lengths.median():.0f} / "
            f"{lengths.quantile(0.9):.0f} / {lengths.quantile(0.99):.0f} / {lengths.max():.0f}"
        )
        r(f"  under {SHORT_NOTE_CHARS} chars: {(lengths < SHORT_NOTE_CHARS).mean():.1%}")
        for marker in CR_ARTEFACTS:
            r(f"  contains {marker!r}: {notes.str.contains(marker, regex=False).mean():.1%}")
        if cols["industry"]:
            by = pd.DataFrame(
                {"v": df.loc[notes.index, cols["industry"]], "n": lengths}
            ).groupby("v")["n"].median()
            r("  median length per vertical:")
            for v, m in by.sort_values(ascending=False).items():
                r(f"    {m:>6.0f}  {v}")

    if cols["topics"]:
        per_row = df[cols["topics"]].map(_split_topics)
        counts = Counter(t for ts in per_row for t in ts)
        r.h(f"{cols['topics']} (pre-call topics)")
        r(f"  distinct titles: {len(counts):,}")
        r("  topics per row: " + ", ".join(
            f"{k}={v:,}" for k, v in sorted(Counter(map(len, per_row)).items())[:10]
        ))
        r("  title prefixes (first word):")
        for p, n in Counter(_prefix(t) for t in counts.elements()).most_common(20):
            r(f"    {n:>9,}  {p}")
        r("  most common titles:")
        for title, n in counts.most_common(25):
            r(f"    {n:>9,}  {title}")

    return df.rename(columns={v: k for k, v in cols.items() if v})


def profile_topics(r: Report, path: Path, events: pd.DataFrame | None) -> None:
    r.h(f"Campaign Topics: {path.name}")
    reg = _read_table(path)
    r(f"rows: {len(reg):,}   columns: {list(reg.columns)}")
    name_col = _find(list(reg.columns), "name")
    ind_col = _find(list(reg.columns), "industry")
    desc_col = _find(list(reg.columns), "description")
    if not name_col:
        r("  no Name column -- cannot check matching")
        return

    names = reg[name_col].dropna().str.strip()
    r(f"  distinct names: {names.nunique():,}   duplicated names: {names.duplicated().sum():,}")
    r(f"  names containing a comma: {names.str.contains(',').sum()}  "
      "(these would break comma-splitting of pre-call topics)")
    if desc_col:
        lengths = reg[desc_col].dropna().str.len()
        r(f"  description length p50 / p90 / max: "
          f"{lengths.median():.0f} / {lengths.quantile(0.9):.0f} / {lengths.max():.0f}")
    if ind_col:
        r(f"\n  {ind_col} values:")
        r.counts(reg[ind_col])
        r("\n  name prefix x industry:")
        pairs = Counter(zip(names.map(_prefix), reg.loc[names.index, ind_col], strict=True))
        for (p, ind), n in pairs.most_common(30):
            r(f"    {n:>6,}  {p:<8} {ind}")

    if events is None or "topics" not in events:
        return
    registry = set(names)
    counts = Counter(t for ts in events["topics"].map(_split_topics) for t in ts)
    total = sum(counts.values())
    matched = sum(n for t, n in counts.items() if t in registry)
    r.h("Pre-call topics vs Campaign Topics (exact match)")
    r(f"  distinct titles matched: {sum(t in registry for t in counts):,} / {len(counts):,}")
    r(f"  mentions matched:        {matched:,} / {total:,} ({matched / max(total, 1):.1%})")
    r("  most common unmatched:")
    for title, n in [(t, n) for t, n in counts.most_common() if t not in registry][:20]:
        r(f"    {n:>9,}  {title}")

    if ind_col and "industry" in events:
        lookup = dict(zip(names, reg.loc[names.index, ind_col], strict=True))
        pairs: Counter[tuple[str, str]] = Counter()
        for acct, ts in zip(
            events["industry"], events["topics"].map(_split_topics), strict=True
        ):
            for t in ts:
                if t in lookup:
                    pairs[(str(acct), str(lookup[t]))] += 1
        r.h("Account.Industry vs the topic's Industry__c (matched topics only)")
        r("  does a visit's vertical agree with its topics' vertical?")
        for (acct, ind), n in pairs.most_common(30):
            r(f"    {n:>9,}  account={acct:<28} topic={ind}")


def profile_must_capture(r: Report, path: Path) -> None:
    r.h(f"Must-capture workbook: {path.name}")
    book = pd.read_excel(path, engine="openpyxl", sheet_name=None, header=None, dtype=str)
    r(f"tabs: {list(book)}")
    for name, sheet in book.items():
        lowered = name.lower()
        if "method" in lowered or "sign" in lowered:
            r(f"\n### Tab: {name}\n")
            for row in sheet.itertuples(index=False):
                cells = [str(c).strip() for c in row if isinstance(c, str) and c.strip()]
                if cells:
                    r("    " + " | ".join(cells))
            continue
        # Field tabs: has anyone filled in the Business decision column?
        header_row = next(
            (i for i, row in sheet.iterrows()
             if any(isinstance(c, str) and c.strip().lower() == "business decision" for c in row)),
            None,
        )
        if header_row is None:
            continue
        headers = [str(c).strip() if isinstance(c, str) else "" for c in sheet.iloc[header_row]]
        body = sheet.iloc[header_row + 1 :].copy()
        body.columns = headers
        decisions = body["Business decision"].dropna().str.strip()
        decisions = decisions[decisions != ""]
        comments = body.get("Comments", pd.Series(dtype=str)).dropna().str.strip()
        r(f"\n  {name}: {len(decisions)} decisions filled, "
          f"{(comments != '').sum()} comments")
        if len(decisions):
            r.counts(decisions)


def main() -> None:
    ap = argparse.ArgumentParser(description="Profile the AIML-2898 source files.")
    ap.add_argument("--raw", type=Path, default=RAW, help="folder holding the three files")
    ap.add_argument("--events", type=Path)
    ap.add_argument("--topics", type=Path)
    ap.add_argument("--must-capture", type=Path)
    ap.add_argument("--out", type=Path, default=OUT / "profile_report.md")
    args = ap.parse_args()

    events_path = args.events or _discover(args.raw, "Event*")
    topics_path = args.topics or _discover(args.raw, "*Topic*")
    must_path = args.must_capture or _discover(args.raw, "must-capture*.xlsx")

    r = Report()
    r("# AIML-2898 source profile")
    r(f"\nevents: {events_path}\ntopics: {topics_path}\nmust-capture: {must_path}")

    # Each section is independent: a problem with one file is reported and the
    # rest of the report still gets written, so one run is always enough.
    def section(label: str, path: Path | None, fn, *fn_args):
        if not path:
            r.h(f"{label}: file not found in {args.raw}")
            return None
        try:
            return fn(r, path, *fn_args)
        except Exception as exc:
            r.h(f"{label}: FAILED")
            r(f"    {type(exc).__name__}: {exc}")
            return None

    events = section("events", events_path, profile_events)
    section("topics", topics_path, profile_topics, events)
    section("must-capture", must_path, profile_must_capture)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(r.lines) + "\n", encoding="utf-8")
    print(f"\nReport written to {args.out}")


if __name__ == "__main__":
    main()
