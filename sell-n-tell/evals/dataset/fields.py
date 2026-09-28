"""Must-capture field catalog, loaded from the business review sheet.

Source: ``must-capture-fields.xlsx``, the "Universal Fields" and "Must-Capture
by Vertical" tabs, exported to CSV as-is into ``resources/``. Kept as the
delivered CSVs rather than re-typed into Python or YAML so a revised sheet can
be dropped in without hand-editing -- re-export the two tabs and overwrite.

Every golden record is labelled against ``catalog.fields_for(vertical)``: the
11 universal fields plus the 9 for the record's vertical. Priority travels with
each field because the eval scorecard groups extraction metrics by priority.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

RESOURCES = Path(__file__).parent / "resources"
UNIVERSAL_CSV = RESOURCES / "universal_fields.csv"
VERTICAL_CSV = RESOURCES / "vertical_fields.csv"

UNIVERSAL = "UNIVERSAL"

_FIELD_ID = re.compile(r"^(?:U|[A-Z]{2})-\d{2}$")
# The vertical tab has one banner row per vertical, with the "what governs the
# buy" summary sitting in the Field ID column and volume stats after a "|".
_GOVERNS_PREFIX = "What governs the buy:"


@dataclass(frozen=True)
class Field:
    field_id: str
    name: str
    captures: str
    priority: int
    vertical: str  # UNIVERSAL, or a vertical code such as "MH"


@dataclass(frozen=True)
class Vertical:
    code: str  # "MH"
    name: str  # "Multifamily"
    governs_the_buy: str


@dataclass(frozen=True)
class Catalog:
    universal: tuple[Field, ...]
    verticals: dict[str, Vertical]
    by_vertical: dict[str, tuple[Field, ...]]

    def fields_for(self, vertical_code: str) -> tuple[Field, ...]:
        """Universal fields followed by the vertical's own fields."""
        if vertical_code not in self.by_vertical:
            raise KeyError(
                f"Unknown vertical {vertical_code!r}; "
                f"expected one of {sorted(self.by_vertical)}"
            )
        return self.universal + self.by_vertical[vertical_code]

    @property
    def all_fields(self) -> tuple[Field, ...]:
        return self.universal + tuple(
            f for code in self.by_vertical for f in self.by_vertical[code]
        )


def _split_vertical(label: str) -> tuple[str, str]:
    """``"MH - Multifamily"`` -> ``("MH", "Multifamily")``."""
    code, sep, name = label.partition(" - ")
    if not sep or not code.strip() or not name.strip():
        raise ValueError(f"Unrecognised vertical label: {label!r}")
    return code.strip(), name.strip()


def _priority(row: dict[str, str], field_id: str) -> int:
    raw = (row.get("Priority") or "").strip()
    if not raw.isdigit():
        raise ValueError(f"{field_id}: missing or non-numeric priority {raw!r}")
    return int(raw)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_universal(path: Path = UNIVERSAL_CSV) -> tuple[Field, ...]:
    fields = []
    for row in _read_rows(path):
        field_id = (row.get("Field ID") or "").strip()
        if not _FIELD_ID.match(field_id):
            continue
        fields.append(
            Field(
                field_id=field_id,
                name=row["Field"].strip(),
                captures=row["What the agent captures"].strip(),
                priority=_priority(row, field_id),
                vertical=UNIVERSAL,
            )
        )
    return tuple(fields)


def load_verticals(
    path: Path = VERTICAL_CSV,
) -> tuple[dict[str, Vertical], dict[str, tuple[Field, ...]]]:
    verticals: dict[str, Vertical] = {}
    fields: dict[str, list[Field]] = {}
    for row in _read_rows(path):
        label = (row.get("Vertical") or "").strip()
        if not label:
            continue
        code, name = _split_vertical(label)
        cell = (row.get("Field ID") or "").strip()

        if cell.startswith(_GOVERNS_PREFIX):
            governs = cell.split("|", 1)[0][len(_GOVERNS_PREFIX) :].strip()
            verticals[code] = Vertical(code, name, governs)
            continue
        if not _FIELD_ID.match(cell):
            continue
        fields.setdefault(code, []).append(
            Field(
                field_id=cell,
                name=row["Field"].strip(),
                captures=row["What the agent captures"].strip(),
                priority=_priority(row, cell),
                vertical=code,
            )
        )

    missing_banner = set(fields) - set(verticals)
    if missing_banner:
        raise ValueError(f"Fields for verticals with no banner row: {missing_banner}")
    return verticals, {code: tuple(fs) for code, fs in fields.items()}


def load_catalog() -> Catalog:
    verticals, by_vertical = load_verticals()
    return Catalog(
        universal=load_universal(), verticals=verticals, by_vertical=by_vertical
    )
