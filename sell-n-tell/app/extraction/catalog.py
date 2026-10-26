"""The must-capture field catalog: which fields a record has, per vertical.

Read from the two catalog CSVs (reference data, kept with the golden set):
``universal_fields.csv`` (the 11 universal fields) and ``vertical_fields.csv``
(9 per vertical, with one heading row per vertical that carries no field id).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

VERTICALS = ("MH", "HS", "HL", "IS", "TR", "IN")
# U-03 is the per-topic status, which the record carries as its topics list.
TOPIC_STATUS_FIELD = "U-03"
_FIELD_ID = re.compile(r"^(U|MH|HS|HL|IS|TR|IN)-\d{2}$")


@dataclass(frozen=True)
class Field:
    id: str
    name: str
    captures: str        # "What the agent captures": the field's definition
    priority: int


def load_catalog(folder: Path) -> list[Field]:
    out: list[Field] = []
    for name in ("universal_fields.csv", "vertical_fields.csv"):
        with (folder / name).open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                fid = (row.get("Field ID") or "").strip()
                if _FIELD_ID.match(fid):
                    out.append(Field(fid, (row.get("Field") or "").strip(),
                                     (row.get("What the agent captures") or "").strip(),
                                     int(row["Priority"])))
    return out


def fields_for(catalog: list[Field], vertical: str) -> list[Field]:
    """The universal fields (less the topic status) plus that vertical's own."""
    if vertical not in VERTICALS:
        raise ValueError(f"unknown vertical {vertical!r}; expected one of {VERTICALS}")
    return [f for f in catalog if f.id != TOPIC_STATUS_FIELD
            and (f.id.startswith("U-") or f.id.startswith(f"{vertical}-"))]
