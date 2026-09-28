"""Must-capture field catalog (AIML-2898).

Pins the shape of the business sheet: if a re-exported CSV loses a field,
changes a priority to something non-numeric, or renames a vertical, these fail
before any record gets labelled against the wrong field set.
"""

import pytest

from evals.dataset.fields import UNIVERSAL, load_catalog

VERTICAL_CODES = {"MH", "HS", "HL", "IS", "TR", "IN"}
TOTAL_FIELDS = 65  # 11 universal + 9 x 6 verticals
FIELDS_PER_RECORD = 20  # 11 universal + 9 for the record's vertical


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


def test_eleven_universal_fields(catalog):
    assert [f.field_id for f in catalog.universal] == [
        f"U-{n:02d}" for n in range(1, 12)
    ]
    assert all(f.vertical == UNIVERSAL for f in catalog.universal)


def test_six_verticals_with_nine_fields_each(catalog):
    assert set(catalog.verticals) == VERTICAL_CODES
    assert set(catalog.by_vertical) == VERTICAL_CODES
    for code, fields in catalog.by_vertical.items():
        assert [f.field_id for f in fields] == [
            f"{code}-{n:02d}" for n in range(1, 10)
        ]


def test_sixty_five_fields_in_total(catalog):
    assert len(catalog.all_fields) == TOTAL_FIELDS
    assert len({f.field_id for f in catalog.all_fields}) == TOTAL_FIELDS


def test_every_field_has_a_priority_between_one_and_three(catalog):
    assert {f.priority for f in catalog.all_fields} <= {1, 2, 3}


def test_fields_for_a_vertical_is_universal_then_vertical(catalog):
    fields = catalog.fields_for("MH")
    assert len(fields) == FIELDS_PER_RECORD
    assert fields[0].field_id == "U-01"
    assert fields[-1].field_id == "MH-09"


def test_vertical_banner_is_parsed(catalog):
    mh = catalog.verticals["MH"]
    assert mh.name == "Multifamily"
    assert mh.governs_the_buy.startswith("Cost per unit turn")
    assert "|" not in mh.governs_the_buy


def test_unknown_vertical_is_refused(catalog):
    with pytest.raises(KeyError):
        catalog.fields_for("XX")
