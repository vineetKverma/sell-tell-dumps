"""U-02 key fix: filled only where the key shows an interaction and U-02 is
blank and uncontested; never on golden v1.1 (whose blanks mean 'unknown')."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evals.dataset.fix_contact_outcome import VALUE, apply  # noqa: E402
from evals.dataset.fix_event_types import stage_args  # noqa: E402


def _case(cid, event, u02=None, contested=()):
    return {"eval_id": cid, "conversation": [{"intermediate_data": {"tool_uses": [
        {"name": "stage_visit_notes", "args": {"event_type": event, "contested": list(contested),
                                               "must_capture": {"U-02": u02}}}]}}]}


def test_u02_is_filled_only_where_the_rep_interacted_and_it_was_blank():
    data = {"eval_set_id": "sellntell_golden_v1.2", "eval_cases": [
        _case("A", "Meeting"), _case("B", "Phone Call"),
        _case("C", "On-site visit"), _case("D", None),                       # no interaction
        _case("E", "Meeting", "no contact"), _case("F", "Meeting", "spoke with alternate"),
        _case("G", "Meeting", contested=["U-02"])]}
    out, changed = apply(data)
    assert changed == ["A"]
    got = {c["eval_id"]: stage_args(c)["must_capture"]["U-02"] for c in out["eval_cases"]}
    assert got["A"] == VALUE
    assert got["B"] is None                                                  # a call can end at a voicemail
    assert got["C"] is None and got["D"] is None and got["G"] is None
    assert got["E"] == "no contact" and got["F"] == "spoke with alternate"   # never overwritten


def test_a_second_run_is_refused_and_writes_nothing(tmp_path, monkeypatch):
    import json

    import pytest

    from evals.dataset import fix_contact_outcome as fix
    src = tmp_path / "golden_v1.evalset.json"
    src.write_text(json.dumps({"eval_set_id": "sellntell_golden_v1.2", "description": "d",
                               "eval_cases": [_case("A", "Meeting"), _case("C", "On-site visit")]}), encoding="utf-8")
    out = tmp_path / "v13"
    monkeypatch.setattr(sys, "argv", ["fix", str(src), str(out)])
    fix.main()
    manifest = next(out.glob("*.manifest.json"))
    first = manifest.read_bytes()
    assert json.loads(first)["cases"] == ["A"]

    # Run on its own output: refused, and the manifest keeps its list of cases.
    monkeypatch.setattr(sys, "argv", ["fix", str(out / src.name), str(out)])
    with pytest.raises(SystemExit, match="expected sellntell_golden_v1.2"):
        fix.main()
    assert manifest.read_bytes() == first

    # Any key but golden v1.2 is refused and writes nothing, whatever the label.
    monkeypatch.setattr(sys, "argv", ["fix", str(out / src.name), str(tmp_path / "v14")])
    with pytest.raises(SystemExit, match="expected sellntell_golden_v1.2"):
        fix.main()
    assert not (tmp_path / "v14").exists()


def test_blank_means_what_the_scorer_means_and_missing_fields_do_not_crash():
    no_fields = _case("H", "Meeting")
    stage_args(no_fields)["must_capture"] = None                             # null in the key
    data = {"eval_set_id": "set_v1.2", "eval_cases": [_case("G", "Meeting", "Not stated"), no_fields]}
    out, changed = apply(data)
    assert changed == ["G", "H"]
    assert all(stage_args(c)["must_capture"]["U-02"] == VALUE for c in out["eval_cases"])


def test_a_case_that_is_not_changed_is_left_exactly_as_it_was():
    visit = _case("V", "On-site visit")
    stage_args(visit)["must_capture"] = None                                 # null in the key
    out, changed = apply({"eval_set_id": "set_v1.2", "eval_cases": [_case("M", "Meeting"), visit]})
    assert changed == ["M"] and stage_args(out["eval_cases"][1])["must_capture"] is None


def test_a_non_golden_key_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    import json

    import pytest

    from evals.dataset import fix_contact_outcome as fix
    src = tmp_path / "golden_topup_v1.evalset.json"
    src.write_text(json.dumps({"eval_set_id": "sellntell_topup_v1", "eval_cases": [_case("T", "Meeting")]}),
                   encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["fix", str(src), str(tmp_path / "out")])
    with pytest.raises(SystemExit, match="golden v1.2 only"):
        fix.main()
    assert not (tmp_path / "out").exists()

