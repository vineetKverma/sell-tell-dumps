"""Loading the source files, shared by the profilers, sampler and drafter.

Facts established by profiling and relied on here:

- ``Event-9_1_2026.xlsb`` has one sheet, "Precall Notes", and exactly four
  columns: ``Account.Industry``, ``Pre_call_Planning_Objective__c``,
  ``Selected_PCP_Topics__c``, ``Description``. No label columns exist.
- ``Account.Industry`` uses the must-capture sheet's codes ("MH - MULTIFAMILY").
  ``CN - CONSUMER`` (31 rows) is treated as Multifamily, per the sheet's Method
  tab.
- The Campaign Topics sheet is damaged at source by a Replace All; see
  ``text.REGISTRY_DAMAGE``. ``load_registry`` repairs Name and Description.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from evals.dataset.paths import OUT, RAW
from evals.dataset.text import (  # re-exported for the profilers
    MOJIBAKE_MARKERS,
    VERTICALS,
    RegistryTopic,
    TopicIndex,
    clean_note,
    make_splitter,
    repair_registry_text,
)

COLUMNS = {
    "Account.Industry": "industry",
    "Pre_call_Planning_Objective__c": "objective",
    "Selected_PCP_Topics__c": "topics",
    "Description": "note",
}
# Per the must-capture Method tab: too few calls to profile; behave as MH.
VERTICAL_ALIASES = {"CN": "MH"}

__all__ = [
    "MOJIBAKE_MARKERS",
    "OUT",
    "RAW",
    "VERTICALS",
    "clean_note",
    "load_events",
    "load_registry",
    "make_splitter",
    "topic_index",
    "vertical_code",
]


def _find_one(raw: Path, pattern: str) -> Path:
    hits = sorted(p for p in raw.glob(pattern) if p.is_file())
    if not hits:
        raise FileNotFoundError(f"No file matching {pattern!r} in {raw}")
    return hits[0]


def vertical_code(industry: object) -> str | None:
    """``"MH - MULTIFAMILY"`` -> ``"MH"``; unknown or empty -> None."""
    if not isinstance(industry, str) or " - " not in industry:
        return None
    code = industry.split(" - ", 1)[0].strip().upper()
    code = VERTICAL_ALIASES.get(code, code)
    return code if code in VERTICALS else None


def load_events(raw: Path = RAW, refresh: bool = False) -> pd.DataFrame:
    """The events sheet with short column names and a ``vertical`` code.

    The .xlsb takes minutes to parse, so the first load writes a parquet cache
    beside the raw files (same gitignored folder) and later loads read that.
    """
    cache = raw.parent / "cache" / "events.parquet"
    if cache.exists() and not refresh:
        return pd.read_parquet(cache)
    path = _find_one(raw, "Event*")
    engine = "pyxlsb" if path.suffix.lower() == ".xlsb" else "openpyxl"
    df = pd.read_excel(path, engine=engine, sheet_name=0, dtype=str)
    missing = set(COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} is missing columns {sorted(missing)}")
    df = df[list(COLUMNS)].rename(columns=COLUMNS)
    df["vertical"] = df["industry"].map(vertical_code)
    cache.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache)
    return df


def load_registry(raw: Path = RAW, repair: bool = True) -> pd.DataFrame:
    """Campaign Topics with columns name / description / industry.

    ``repair=True`` undoes the source Replace All damage in name and
    description; the damaged originals are kept as ``name_raw`` /
    ``description_raw``.
    """
    path = _find_one(raw, "*Topic*")
    if path.suffix.lower() == ".csv":
        for enc in ("utf-8-sig", "cp1252"):
            try:
                reg = pd.read_csv(path, encoding=enc, dtype=str)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError(f"{path}: neither UTF-8 nor cp1252")
    else:
        reg = pd.read_excel(path, engine="openpyxl", dtype=str)
    reg = reg.rename(
        columns={"Name": "name", "Description": "description", "Industry__c": "industry"}
    )
    reg["name"] = reg["name"].fillna("").str.strip()
    reg["name_raw"] = reg["name"]
    reg["description_raw"] = reg["description"]
    if repair:
        reg["name"] = reg["name"].map(repair_registry_text).str.strip()
        reg["description"] = reg["description"].map(repair_registry_text)
    return reg[reg["name"] != ""]


def topic_index(reg: pd.DataFrame) -> TopicIndex:
    return TopicIndex(
        [
            RegistryTopic(
                str(n),
                d if isinstance(d, str) else "",
                i if isinstance(i, str) else "",
            )
            for n, d, i in zip(reg["name"], reg["description"], reg["industry"], strict=True)
        ]
    )
