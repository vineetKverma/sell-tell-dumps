"""AIML-2929 extract(): schema, evidence check, settling the record, scoring
mapping. No model and no credentials: the Gemini client is a stand-in."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.extraction import (  # noqa: E402
    DISCUSSED, NOT_DISCUSSED, UNCONFIRMED, Field, build_prompt, extract, fields_for, load_catalog,
    postprocess, quote_in, record_model,
)
from evals.agent_eval.cases import GOLDEN_DIR  # noqa: E402

CATALOG = [Field("U-01", "Contact identity", "Name and role.", 1),
           Field("U-03", "Topic status", "Per topic.", 1),
           Field("U-04", "Commercial outcome", "Order or quote.", 1),
           Field("MH-01", "Turns per month", "Units turning.", 1),
           Field("HS-01", "Department and role", "Which department.", 1)]
NOTE = "Shared mini fridge pricing with Frank. He wants a quote for 6 units."
PLANNED = ["2026 Q2 Compact Appliances Hospitality", "MF Pools 26"]


def raw(**over):
    base = {"event_type": "Meeting", "executive_summary": "Shared fridge pricing with Frank.",
            "topics": [{"topic": PLANNED[0], "status": "discussed",
                        "evidence": "shared mini fridge pricing with Frank", "summary": "Pricing shared."},
                       {"topic": PLANNED[1], "status": "not_discussed", "evidence": "", "summary": ""}],
            "must_capture": {"U_01": "Frank", "U_04": "not stated", "HS_01": None}}
    base.update(over)
    return base


# --- catalog ------------------------------------------------------------------

def test_a_vertical_gets_the_universal_fields_and_only_its_own():
    ids = [f.id for f in fields_for(CATALOG, "HS")]
    assert ids == ["U-01", "U-04", "HS-01"]                 # no U-03 (topics), no MH-01
    with pytest.raises(ValueError):
        fields_for(CATALOG, "XX")


@pytest.mark.skipif(not (GOLDEN_DIR / "universal_fields.csv").exists(), reason="field catalog not present")
def test_every_vertical_has_19_fields_from_the_real_catalog():
    catalog = load_catalog(GOLDEN_DIR)
    for v in ("MH", "HS", "HL", "IS", "TR", "IN"):
        fields = fields_for(catalog, v)
        assert len(fields) == 19, v                        # 10 universal (less U-03) + 9 vertical
        assert all(f.captures for f in fields)


# --- schema -------------------------------------------------------------------

def test_schema_fixes_the_shape_and_every_field_is_optional():
    model = record_model(fields_for(CATALOG, "HS"))
    ok = model.model_validate({"event_type": "Meeting", "executive_summary": "s",
                               "topics": [], "must_capture": {}})
    assert ok.must_capture.U_01 is None                     # optional, null by default
    for bad in ({"event_type": "Lunch", "executive_summary": "s", "topics": [], "must_capture": {}},
                {"executive_summary": "s", "topics": [], "must_capture": {}},
                {"event_type": "Meeting", "executive_summary": "s",
                 "topics": [{"topic": "x", "status": "maybe"}], "must_capture": {}}):
        with pytest.raises(Exception):
            model.model_validate(bad)


# --- the evidence check -------------------------------------------------------

@pytest.mark.parametrize("quote,ok", [
    ("shared mini fridge pricing with Frank", True),
    ("Shared  mini fridge\npricing", True),                 # case and spacing ignored
    ("“mini fridge pricing”", True),             # curly quotes ignored
    ("mini fridge pricing ... a quote for 6 units", True),   # parts around an ellipsis
    ("compact appliances campaign", False),                  # not the rep's words
    ("mini fridge pricing ... ordered 10 units", False),     # one part invented
    ("", False), ("Fr", False),                               # empty or too short
    ("a ... e ... i ... o", False),                          # loose letters are not the rep's words
    ("s ... h ... a ... r", False),
    ("units ... Shared", False),                             # real words, stitched out of order
    ("ridge pricing", False),                                # cut mid-word
    ("a ... 6", False), ("He ... a ... for", False),         # whole words in order, but too small to be evidence
    ("mini fridge", True), ("6 units", True),                 # short but whole words, in the note
])
def test_a_quote_counts_only_if_the_rep_said_it(quote, ok):
    assert quote_in(quote, NOTE) is ok


# --- settling the record --------------------------------------------------------

def test_a_discussed_topic_keeps_its_status_only_with_real_evidence():
    r = postprocess(raw(), NOTE, PLANNED)
    assert [t["status"] for t in r.record["topics"]] == [DISCUSSED, NOT_DISCUSSED]
    assert r.unconfirmed == []

    invented = raw(topics=[{"topic": PLANNED[0], "status": "discussed",
                            "evidence": "they want the compact appliance promo", "summary": "s"}])
    r = postprocess(invented, NOTE, PLANNED)
    assert r.record["topics"][0]["status"] == UNCONFIRMED and r.unconfirmed == [PLANNED[0]]
    assert r.record["topics"][0]["evidence"] == ""        # an unverified quote is not kept


def test_a_left_out_topic_is_not_discussed_and_an_unknown_label_is_off_plan():
    r = postprocess(raw(topics=[{"topic": "Range hoods", "status": "discussed", "evidence": "Frank", "summary": ""}]),
                    NOTE, PLANNED)
    assert [t["status"] for t in r.record["topics"]] == [NOT_DISCUSSED, NOT_DISCUSSED]
    assert r.off_plan == ["Range hoods"]


def test_the_schema_allows_only_the_planned_labels():
    model = record_model(fields_for(CATALOG, "HS"), PLANNED)
    ok = {"event_type": "Meeting", "executive_summary": "s", "must_capture": {},
          "topics": [{"topic": PLANNED[0], "status": "discussed", "evidence": "x"}]}
    model.model_validate(ok)
    # The failure seen on the first full run: the label copied with its description.
    with pytest.raises(Exception):
        model.model_validate(dict(ok, topics=[{"topic": f"{PLANNED[0]}: Compact fridges and microwaves.",
                                               "status": "discussed"}]))


def test_a_label_with_its_description_attached_still_matches():
    with_desc = raw(topics=[{"topic": f"{PLANNED[0]}: Compact fridges and microwaves.", "status": "discussed",
                             "evidence": "mini fridge pricing", "summary": "s"}])
    r = postprocess(with_desc, NOTE, PLANNED)
    assert r.record["topics"][0]["status"] == DISCUSSED and r.off_plan == []


def test_labels_match_ignoring_case_and_duplicates_do_not_add_rows():
    dup = raw(topics=[{"topic": PLANNED[0].upper(), "status": "discussed",
                       "evidence": "mini fridge pricing", "summary": ""},
                      {"topic": PLANNED[0], "status": "not_discussed", "evidence": "", "summary": ""}])
    topics = postprocess(dup, NOTE, PLANNED).record["topics"]
    assert len(topics) == 2 and topics[0]["status"] == DISCUSSED


def test_a_count_with_no_number_is_dropped():
    r = postprocess(raw(must_capture={"U_10": "turns", "U_01": "Frank"}), NOTE, PLANNED)
    assert r.record["must_capture"]["U-10"] is None and r.record["must_capture"]["U-01"] == "Frank"
    r = postprocess(raw(must_capture={"U_10": "2-4/month stackables"}), NOTE, PLANNED)
    assert r.record["must_capture"]["U-10"] == "2-4/month stackables"
    for spelled in ("twelve units", "a dozen keys", "Two hundred beds"):       # a number in words counts
        assert postprocess(raw(must_capture={"U_10": spelled}), NOTE, PLANNED).record["must_capture"]["U-10"] == spelled


def test_a_title_planned_twice_is_one_topic():
    twice = [PLANNED[0], PLANNED[0], PLANNED[1]]
    r = postprocess(raw(), NOTE, twice)
    assert [t["topic"] for t in r.record["topics"]] == PLANNED
    record_model(fields_for(CATALOG, "HS"), twice)                             # the schema builds too


def test_a_bad_setup_is_an_error_result_not_a_crash():
    pytest.importorskip("google.genai")
    r = extract(NOTE, PLANNED, "HS", None, client=FakeClient(json.dumps(raw())), model="m")   # no field list
    assert r.record is None and r.error and "seconds" in r.usage


def test_not_stated_values_become_null_and_ids_get_their_dashes_back():
    fields = postprocess(raw(), NOTE, PLANNED).record["must_capture"]
    assert fields == {"U-01": "Frank", "U-04": None, "HS-01": None}


# --- the call -----------------------------------------------------------------

class FakeClient:
    """Stands in for google.genai.Client: returns ``reply`` (or raises it)."""

    def __init__(self, reply):
        self.prompts = []
        outer = self

        class Models:
            def generate_content(self, *, model, contents, config):
                outer.prompts.append(contents)
                outer.config = config
                if isinstance(reply, Exception):
                    raise reply
                return type("Resp", (), {"text": reply})()
        self.models = Models()


def test_extract_returns_the_settled_record_and_sends_a_schema():
    pytest.importorskip("google.genai")
    client = FakeClient(json.dumps(raw()))
    r = extract(NOTE, PLANNED, "HS", fields_for(CATALOG, "HS"), client=client, model="m")
    assert r.error is None and r.record["event_type"] == "Meeting"
    assert client.config.response_schema is not None and client.config.temperature == 0


def test_every_call_records_its_tokens_and_time_even_a_failed_one():
    pytest.importorskip("google.genai")
    from app.extraction.extract import usage_of
    meta = type("M", (), {"prompt_token_count": 1200, "candidates_token_count": 300, "thoughts_token_count": 50})()
    assert usage_of(type("R", (), {"usage_metadata": meta})(), 1.234) == {
        "input_tokens": 1200, "output_tokens": 300, "thinking_tokens": 50, "seconds": 1.23}
    assert usage_of(type("R", (), {})(), 0.5)["input_tokens"] == 0          # no metadata: zeros, not a crash

    class Reply:
        text, usage_metadata = "not json", meta
    client = FakeClient("x")
    client.models.generate_content = lambda **kw: Reply()
    r = extract(NOTE, PLANNED, "HS", fields_for(CATALOG, "HS"), client=client, model="m")
    assert r.error and r.usage["input_tokens"] == 1200                       # a bad reply still cost tokens


def test_thinking_is_a_level_or_a_budget_and_reaches_the_call():
    pytest.importorskip("google.genai")
    from app.extraction.extract import thinking_config
    assert thinking_config(None) is None
    assert thinking_config("low").thinking_level.value == "LOW"
    assert thinking_config("0").thinking_budget == 0 and thinking_config(512).thinking_budget == 512
    client = FakeClient(json.dumps(raw()))
    extract(NOTE, PLANNED, "HS", fields_for(CATALOG, "HS"), client=client, model="m", thinking="minimal")
    assert client.config.thinking_config.thinking_level.value == "MINIMAL"


def test_a_reply_that_does_not_fit_the_schema_is_an_error_never_repaired():
    pytest.importorskip("google.genai")
    for reply in ("not json", json.dumps(raw(event_type="Lunch")), json.dumps({"topics": []}),
                  TimeoutError("connect timeout")):
        r = extract(NOTE, PLANNED, "HS", fields_for(CATALOG, "HS"), client=FakeClient(reply), model="m")
        assert r.record is None and r.error, reply


def test_the_prompt_carries_the_rules_the_descriptions_and_the_note():
    p = build_prompt(NOTE, PLANNED, "HS", {PLANNED[0]: "Compact fridges and countertop microwaves."})
    assert "Phone Call" in p and "named or not" in p and "not available" in p   # event-type rule
    assert "conversation about the business with someone at the" in p           # Meeting (Tobi, 2026-10-14)
    assert "front desk, a receptionist or another gatekeeper" in p               # ... not the front desk
    assert "interacting with anyone" not in p                                   # the old rule
    assert "offer or its products" in p and "verbatim" in p                      # topic rule + evidence
    assert "4x4" in p and "trucks" in p                                          # approved field rules
    assert '"action | owner | date"' in p and "Record the action even with no owner" in p   # next step (U-09)
    assert f"label: {PLANNED[0]}\n   about: Compact fridges and countertop microwaves." in p
    assert f"label: {PLANNED[1]}\n   about: (no description; judge by the label)" in p
    assert "never the description" in p
    assert NOTE in p and "Account vertical: HS" in p


# --- scoring the record -------------------------------------------------------

def test_only_a_confirmed_discussed_topic_scores_as_discussed():
    from evals.extract_eval.run import to_scorer_args
    rec = postprocess(raw(topics=[{"topic": PLANNED[0], "status": "discussed",
                                   "evidence": "the compact appliance promo", "summary": "s"}]),
                      NOTE, PLANNED).record
    args = to_scorer_args(rec)
    assert [t["discussed"] for t in args["topics"]] == [False, False]    # unconfirmed is not discussed
    assert args["must_capture"]["U-01"] == "Frank" and to_scorer_args(None) is None


def test_the_labelling_models_are_refused():
    from evals.extract_eval import run
    assert set(run.LABELLING_MODELS) == {"gemini-3.8-flash", "gemini-3.1-pro-preview"}



def test_a_verbatim_quote_passes_when_the_reps_own_note_has_an_ellipsis():
    note = "Ok... he wants 6 units of the mini fridge"
    assert quote_in("Ok... he wants 6 units", note) is True      # found whole, before any splitting
    assert quote_in("Ok… he wants 6 units", note) is True        # the model typed one character for it
    assert quote_in("Ok... he wants 9 units", note) is False     # still has to be the rep's words


def test_extract_never_raises_and_says_which_kind_of_error():
    pytest.importorskip("google.genai")
    fields = fields_for(CATALOG, "HS")
    none_planned = extract(NOTE, None, "HS", fields, client=FakeClient(json.dumps(raw(topics=[]))), model="m")
    assert none_planned.error is None and none_planned.record["topics"] == []
    assert extract(NOTE, PLANNED, "HS", fields, client=FakeClient(TimeoutError("t")), model="m").error_kind == "call"
    assert extract(NOTE, PLANNED, "HS", fields, client=FakeClient("not json"), model="m").error_kind == "reply"

    class OddUsage:                                              # metadata of an unexpected shape
        text, usage_metadata = json.dumps(raw()), type("M", (), {"prompt_token_count": "many"})()
    client = FakeClient("x")
    client.models.generate_content = lambda **kw: OddUsage()
    r = extract(NOTE, PLANNED, "HS", fields, client=client, model="m")
    assert r.record is None and r.error_kind == "internal" and "seconds" in r.usage   # our code, not the model


def test_a_bug_in_settling_the_record_is_not_scored_as_the_models_miss(monkeypatch):
    pytest.importorskip("google.genai")
    import importlib
    extract_mod = importlib.import_module("app.extraction.extract")   # the module, not the function

    def broken(*_a, **_kw):
        raise KeyError("status")
    monkeypatch.setattr(extract_mod, "postprocess", broken)
    r = extract(NOTE, PLANNED, "HS", fields_for(CATALOG, "HS"), client=FakeClient(json.dumps(raw())), model="m")
    assert r.record is None and r.error_kind == "internal" and "settling the record failed" in r.error


def test_two_titles_that_differ_only_in_case_keep_their_own_status():
    planned = ["MF Pools 26", "mf pools 26"]
    r = postprocess(raw(topics=[
        {"topic": planned[0], "status": "not_discussed", "evidence": "", "summary": ""},
        {"topic": planned[1], "status": "discussed", "evidence": "mini fridge pricing", "summary": "s"}]),
        NOTE, planned)
    assert [(t["topic"], t["status"]) for t in r.record["topics"]] == [
        (planned[0], NOT_DISCUSSED), (planned[1], DISCUSSED)]
