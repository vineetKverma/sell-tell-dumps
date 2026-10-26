"""The campaign registry: a short description for each planned topic.

Read from the Campaign Topics export (``Name``, ``Description``,
``Industry__c``). That file is damaged at source by a Replace All that put
the industry labels inside names and descriptions ("MF Pools 26" became
"MH - MULTIFAMILY Pools 26"); ``repair`` undoes it, as the dataset code did
(evals/dataset/text.py). A title listed for several verticals resolves to the
row tagged with the visit's own vertical.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

# Damaged text -> original. Order matters only in that none overlaps another.
REGISTRY_DAMAGE = {
    "HS - HOSPITALITY": "Hosp",
    "IN - INDUSTRIAL": "Inst",
    "MH - MULTIFAMILY": "MF",
    "IS - PUBLIC SECTOR": "gov",
}
SKIP_TITLES = {"do not use"}
SHORT_DESCRIPTION_CHARS = 300
_URL = re.compile(r"https?://\S+")
_GUIDE_LABEL = re.compile(r"\b(?:seller|user) guid(?:e|ance)\s*:\s*", re.IGNORECASE)


def repair(text: str | None) -> str:
    text = text or ""
    for damaged, original in REGISTRY_DAMAGE.items():
        text = text.replace(damaged, original)
    return text


def short_description(text: str, limit: int = SHORT_DESCRIPTION_CHARS) -> str:
    """Links and guide labels removed, whitespace collapsed, cut at a sentence."""
    text = " ".join(_GUIDE_LABEL.sub("", _URL.sub("", text or "")).split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[: end + 1] if end > limit // 3 else cut.rstrip() + "..."


def _key(title: str) -> str:
    return " ".join((title or "").split()).casefold()


@dataclass(frozen=True)
class Campaign:
    title: str
    description: str          # short, repaired
    industry: str


class Registry:
    def __init__(self, campaigns: list[Campaign]) -> None:
        self._by_key: dict[str, list[Campaign]] = {}
        for c in campaigns:
            if _key(c.title) not in SKIP_TITLES:
                self._by_key.setdefault(_key(c.title), []).append(c)

    def __len__(self) -> int:
        return len(self._by_key)

    def lookup(self, title: str, vertical: str | None = None) -> Campaign | None:
        rows = self._by_key.get(_key(title))
        if not rows:
            return None
        for row in rows:
            if vertical and f"{vertical} - " in row.industry:
                return row
        return rows[0]

    def descriptions(self, titles: list[str], vertical: str | None) -> dict[str, str]:
        """{title: short description} for the titles the registry knows."""
        out = {}
        for t in titles:
            c = self.lookup(t, vertical)
            if c and c.description:
                out[t] = c.description
        return out


def load_registry(path: Path) -> Registry:
    """The export is Windows-1252, not UTF-8; both are accepted."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"{path}: neither UTF-8 nor cp1252")
    rows = csv.DictReader(io.StringIO(text, newline=""))
    missing = {"Name", "Description", "Industry__c"} - set(rows.fieldnames or ())
    if missing:     # a renamed column would otherwise give an empty registry, silently
        raise ValueError(f"{path}: no column {', '.join(sorted(missing))}")
    return Registry([Campaign(repair(r.get("Name")).strip(), short_description(repair(r.get("Description"))),
                              (r.get("Industry__c") or "").strip())
                     for r in rows if (r.get("Name") or "").strip()])
