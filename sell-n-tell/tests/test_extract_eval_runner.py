"""AIML-2929 runner end to end with a stand-in model and judge: everything but
the model call (load, registry, extract, score, judge, scorecard, files)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from evals.agent_eval.cases import EVALSET  # noqa: E402

REGISTRY = _ROOT / "evals" / "reference" / "campaign_topics.csv"
# Only the tests that read the golden set or the campaign registry need them;
# the rest (cost, price table, compare table, ...) run anywhere, CI included.
needs_data = pytest.mark.skipif(not (EVALSET.exists() and REGISTRY.exists()),
                                reason="golden data or campaign registry not present")


class EchoModel:
    """Marks every planned topic not discussed, Meeting, no fields -- a valid
    record built from the prompt, so the run exercises the real schema."""

    def __init__(self):
        self.prompts = []
        outer = self

        class Models:
            def generate_content(self, *, model, contents, config):
                outer.prompts.append(contents)
                planned = re.findall(r"^\d+\. label: (.+)$", contents, re.M)
                return type("R", (), {"text": json.dumps({
                    "event_type": "Meeting", "executive_summary": "Visit.",
                    "topics": [{"topic": t, "status": "not_discussed"} for t in planned],
                    "must_capture": {}})})()
        self.models = Models()


class FakeJudge:
    def __init__(self, model=None):
        pass

    def check(self, note, staged):
        return {"faithful": True, "unsupported": []}


@needs_data
def test_runner_end_to_end(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run
    model = EchoModel()
    monkeypatch.setattr(run, "_client", lambda location: model)
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "2", "--limit", "6"])
    run.main()

    out = next(tmp_path.glob("extract-*"))
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    golden = summary["sets"]["golden"]
    assert golden["cases"] == 6 and golden["schema_or_call_errors"] == 0
    assert golden["dropped_topic_labels"] == 0
    assert summary["described_topic_mentions"]["golden"].split("/")[0] == summary["described_topic_mentions"]["golden"].split("/")[1]
    assert len(model.prompts) == 12                                   # 6 cases x 2 runs
    assert all("(no description" not in p for p in model.prompts)     # every planned topic described
    assert golden["scores"]["over_claimed"]["mean"] == 0.0            # nothing claimed
    assert "disposition" not in golden["scores"]                       # n/a, never 0
    assert (out / "scorecard_golden.md").exists() and (out / "raw_golden_r2.jsonl").exists()
    assert "not compared: --limit" in (out / "scorecard_golden.md").read_text(encoding="utf-8")


@needs_data
def test_rescore_uses_the_saved_records_and_makes_no_model_call(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run
    monkeypatch.setattr(run, "_client", lambda location: EchoModel())
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "2", "--limit", "6"])
    run.main()
    out = next(tmp_path.glob("extract-*"))
    before = json.loads((out / "summary.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(run, "_client", lambda location: pytest.fail("a re-score must not call the model"))
    monkeypatch.setattr(judge_mod, "Judge", lambda **k: pytest.fail("a re-score must not call the judge"))
    monkeypatch.setattr(sys, "argv", ["run", "--rescore", str(out)])
    run.main()
    after = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert after["model"] == "stand-in" and "rescored_at" in after
    assert after["sets"]["golden"]["scores"] == before["sets"]["golden"]["scores"]   # same key, same scores


@needs_data
def test_rescore_never_rewrites_the_saved_records(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run
    monkeypatch.setattr(run, "_client", lambda location: EchoModel())
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "1", "--limit", "8"])
    run.main()
    out = next(tmp_path.glob("extract-*"))
    raw_file = out / "raw_golden_r1.jsonl"
    before = raw_file.read_bytes()

    # Re-score with a smaller set loaded (as if the data folder pointed elsewhere).
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    summary["limit"] = 3
    (out / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["run", "--rescore", str(out)])
    run.main()
    assert raw_file.read_bytes() == before                                   # all 8 records still there
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["sets"]["golden"]["cases"] == 3


def test_rescore_rows_follows_a_corrected_key():
    from evals.agent_eval.cases import Case
    from evals.extract_eval.run import rescore_rows
    row = {"id": "X-001", "record": {"event_type": "Meeting", "executive_summary": "s", "topics": [],
                                     "must_capture": {}},
           "score": {"faithful": True, "unsupported": []}}
    old_key = Case(id="X-001", vertical="MH", note="n", planned_topics=[], event_type=None, topics=[], fields={})
    new_key = Case(id="X-001", vertical="MH", note="n", planned_topics=[], event_type="Meeting", topics=[], fields={})
    assert rescore_rows([old_key], [row])[0]["score"]["event_type"]["ok"] is False   # blank read as On-site
    s = rescore_rows([new_key], [row])[0]["score"]
    assert s["event_type"]["ok"] is True and s["faithful"] is True                    # verdict kept


@needs_data
def test_a_labelling_model_runs_only_on_purpose_and_is_marked(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run
    monkeypatch.setattr(run, "_client", lambda location: EchoModel())
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "gemini-3.8-flash", "--allow-labelling-model",
                                      "--judge-model", "gemini-3.1-pro-preview", "--repeats", "1", "--limit", "3"])
    run.main()
    out = next(tmp_path.glob("extract-*"))
    assert "helped label the golden set" in (out / "scorecard_golden.md").read_text(encoding="utf-8")
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["labelled_the_golden_set"] is True and summary["judge_model"] == "gemini-3.1-pro-preview"


@needs_data
def test_a_model_judging_its_own_summaries_is_noted_on_the_scorecard(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run
    monkeypatch.setattr(run, "_client", lambda location: EchoModel())
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "gemini-3.8-flash", "--allow-labelling-model",
                                      "--judge-model", "gemini-3.8-flash", "--repeats", "1", "--limit", "2"])
    run.main()
    card = (next(tmp_path.glob("extract-*")) / "scorecard_golden.md").read_text(encoding="utf-8")
    assert "judged by `gemini-3.8-flash` itself" in card


def test_cost_comes_from_the_price_table_and_is_never_guessed():
    from evals.extract_eval.run import usage_summary
    rows = [{"usage": {"input_tokens": 1000, "output_tokens": 200, "thinking_tokens": 100, "seconds": s}}
            for s in (1.0, 2.0, 3.0, 4.0)]
    priced = usage_summary(rows, "m", {"m": {"input_per_million": 0.5, "output_per_million": 2.0}})
    assert priced["input_tokens_per_note"] == 1000 and priced["output_tokens_per_note"] == 300  # thinking billed
    assert priced["cost_usd"] == pytest.approx((4000 * 0.5 + 1200 * 2.0) / 1e6)
    assert priced["cost_per_1000_notes_usd"] == pytest.approx(1.1)
    assert priced["seconds_p50"] == 3.0
    assert usage_summary(rows, "m", {"m": {"input_per_million": None, "output_per_million": None}})["cost_usd"] is None
    assert usage_summary(rows, "unknown", {})["cost_usd"] is None
    later = usage_summary(rows, "m", {"m": {"input_per_million": 0.5, "output_per_million": 2.0,
                                            "from_2027": {"input_per_million": 1.0, "output_per_million": 4.0}}})
    assert later["cost_per_1000_notes_usd_from_2027"] == pytest.approx(2.2)


def test_the_committed_price_table_is_complete_for_the_models_we_run():
    from evals.extract_eval.run import PRICES
    prices = json.loads(PRICES.read_text(encoding="utf-8"))
    for m in ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-2.5-flash"):
        assert prices[m]["input_per_million"] > 0 and prices[m]["output_per_million"] > 0 and prices[m]["from"]


@needs_data
def test_a_run_where_calls_fail_is_invalid_not_a_regression(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run

    class Rejecting:
        class models:  # noqa: N801
            @staticmethod
            def generate_content(**_kw):
                raise ValueError("400 INVALID_ARGUMENT: thinking level MINIMAL is not supported")

    monkeypatch.setattr(run, "_client", lambda location: Rejecting())
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "1", "--limit", "4"])
    run.main()
    out = next(tmp_path.glob("extract-*"))
    golden = json.loads((out / "summary.json").read_text(encoding="utf-8"))["sets"]["golden"]
    assert "4 of 4 calls failed" in golden["invalid"] and "MINIMAL is not supported" in golden["invalid"]
    card = (out / "scorecard_golden.md").read_text(encoding="utf-8")
    assert "INVALID -- not compared" in card and "REGRESSION" not in card and "improved" not in card


@needs_data
def test_compare_reads_each_runs_own_numbers(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import compare, run
    monkeypatch.setattr(run, "_client", lambda location: EchoModel())
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "2", "--limit", "4", "--thinking", "low"])
    run.main()
    out = next(tmp_path.glob("extract-*"))
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    r = compare.row(out, "golden")
    assert r["model"] == "stand-in" and r["thinking"] == "low" and r["repeats"] == 2
    assert r["topic_status"] == summary["sets"]["golden"]["scores"]["topic_status"]["mean"]
    assert r["key"] == summary["dataset_sha256"][:8] and r["errors"] == 0
    # what decides whether two runs compare is in the row, not only in the run's folder
    assert r["limit"] == 4 and r["labelling_model"] == "no" and r["judge"] == summary["judge_model"]
    assert r["value_acc_P1"] == summary["sets"]["golden"]["value_accuracy"]["P1"]
    assert compare.row(out, "topup") == {"run": out.name, "missing": "no topup set"}
    assert "| stand-in | low |" in compare.table([r])


@needs_data
def test_a_failed_call_is_left_out_of_the_scores_not_scored_as_a_miss(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run

    class OneFailure(EchoModel):
        def __init__(self):
            super().__init__()
            inner, state = self.models.generate_content, {"failed": False}

            def flaky(**kw):
                if not state["failed"]:
                    state["failed"] = True
                    raise TimeoutError("connect timeout")
                return inner(**kw)
            self.models.generate_content = flaky

    monkeypatch.setattr(run, "_client", lambda location: OneFailure())
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(run, "WORKERS", 1)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "1", "--limit", "12"])
    run.main()
    out = next(tmp_path.glob("extract-*"))
    golden = json.loads((out / "summary.json").read_text(encoding="utf-8"))["sets"]["golden"]
    assert golden["schema_or_call_errors"] == 1 and "invalid" not in golden      # 1 of 12 is under the limit
    scored = json.loads((out / "scores_golden.json").read_text(encoding="utf-8"))["cases"][0]
    assert len(scored) == 11 and all(s["staged"] for s in scored)               # the failed one is not a miss


@needs_data
def test_rescore_keeps_the_runs_own_settings(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run
    monkeypatch.setattr(run, "_client", lambda location: EchoModel())
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "1", "--limit", "3", "--thinking", "low"])
    run.main()
    out = next(tmp_path.glob("extract-*"))
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    summary["sets"]["topup"] = {"cases": 65, "note": "scored earlier, raw files gone"}
    (out / "summary.json").write_text(json.dumps(summary), encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["run", "--rescore", str(out)])
    run.main()
    assert "(thinking: low)" in (out / "scorecard_golden.md").read_text(encoding="utf-8")
    after = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert after["thinking"] == "low" and after["sets"]["topup"]["cases"] == 65   # kept, not dropped


def test_the_labelling_models_are_refused_before_any_call(monkeypatch):
    from evals.extract_eval import run
    monkeypatch.setattr(run, "_client", lambda location: pytest.fail("no client for a refused model"))
    monkeypatch.setattr(sys, "argv", ["run", "--model", "gemini-3.8-flash"])
    with pytest.raises(SystemExit, match="labelled the golden set"):
        run.main()


def _case(cid="X-001"):
    from evals.agent_eval.cases import Case
    return Case(id=cid, vertical="MH", note="n", planned_topics=["MF Pools 26"], event_type="Meeting",
                topics=[{"topic": "MF Pools 26", "discussed": True, "disposition_code": 2}],
                fields={"U-01": "Frank"})


def test_a_reply_that_is_not_a_record_is_scored_as_a_miss_and_a_failed_call_is_not(monkeypatch):
    from evals.extract_eval import run

    class Models:
        calls = 0

        def generate_content(self, **_kw):
            Models.calls += 1
            if Models.calls == 1:
                return type("R", (), {"text": "not json"})()
            raise TimeoutError("connect timeout")

    client = type("C", (), {"models": Models()})()
    monkeypatch.setattr(run, "WORKERS", 1)
    bad_reply, failed_call = run.run_once([_case("X-001"), _case("X-002")], [], client, "m", None, FakeJudge())
    assert bad_reply["error_kind"] == "reply" and bad_reply["score"]["staged"] is False
    assert bad_reply["score"]["topics"][0]["status_ok"] is False              # the model's miss
    assert failed_call["error_kind"] == "call" and failed_call["score"] is None
    # A re-score reads them the same way, including rows saved before error_kind existed.
    old_row = {"id": "X-001", "record": None, "error": "reply does not fit the schema: x", "score": None}
    rescored = run.rescore_rows([_case("X-001"), _case("X-002")], [old_row, failed_call])
    assert rescored[0]["score"]["staged"] is False and rescored[1]["score"] is None


def test_cost_and_latency_are_over_the_calls_the_model_answered():
    from evals.extract_eval.run import usage_summary
    ok = {"usage": {"input_tokens": 1000, "output_tokens": 200, "thinking_tokens": 0, "seconds": 2.0}}
    timed_out = {"usage": {"seconds": 120.0}}
    u = usage_summary([ok, ok, timed_out], "m", {"m": {"input_per_million": 1.0, "output_per_million": 1.0}})
    assert u["calls"] == 3 and u["input_tokens_per_note"] == 1000             # not 667
    assert u["answered_calls"] == 2                                          # the calls the cost covers
    assert u["seconds_p95"] == 2.0 and u["cost_per_1000_notes_usd"] == pytest.approx(1.2)


@needs_data
def test_unjudged_summaries_are_counted_and_too_many_take_faithfulness_out(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run

    class DeadJudge(FakeJudge):
        def check(self, note, staged):
            return {"faithful": None, "error": "rate limited"}

    monkeypatch.setattr(run, "_client", lambda location: EchoModel())
    monkeypatch.setattr(judge_mod, "Judge", DeadJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "1", "--limit", "5"])
    run.main()
    out = next(tmp_path.glob("extract-*"))
    golden = json.loads((out / "summary.json").read_text(encoding="utf-8"))["sets"]["golden"]
    assert golden["unjudged_summaries"] == 5 and "faithfulness" not in golden["scores"]
    assert "Summaries not judged: 5 of 5 -- faithfulness not compared" in (
        out / "scorecard_golden.md").read_text(encoding="utf-8")


@needs_data
def test_a_missing_set_stops_the_run_before_any_call_and_each_set_records_its_own_key(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import compare, run
    model = EchoModel()
    monkeypatch.setattr(run, "_client", lambda location: model)
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(run, "SETS_DIR", tmp_path / "sets")                   # no top-up set there
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "1", "--limit", "3",
                                      "--set", "golden", "topup"])
    with pytest.raises(SystemExit, match="No topup set"):
        run.main()
    assert not model.prompts and not (tmp_path / "runs").exists()

    # The top-up comes in rounds of different notes: every round is loaded.
    topup = tmp_path / "sets" / "topup"
    topup.mkdir(parents=True)
    data = json.loads(EVALSET.read_text(encoding="utf-8"))
    (topup / "golden_topup_v1.evalset.json").write_text(json.dumps(data), encoding="utf-8")
    for c in data["eval_cases"]:
        c["eval_id"] = "T2-" + c["eval_id"]
    (topup / "golden_topup_v2.evalset.json").write_text(json.dumps(data), encoding="utf-8")
    assert len(run.set_cases("topup")) == 2 * len(data["eval_cases"])
    run.main()
    out = next((tmp_path / "runs").glob("extract-*"))
    sets = json.loads((out / "summary.json").read_text(encoding="utf-8"))["sets"]
    assert sets["topup"]["cases"] == 3 and len(model.prompts) == 6
    assert sets["golden"]["key_sha256"] != sets["topup"]["key_sha256"]
    assert compare.row(out, "topup")["key"] == sets["topup"]["key_sha256"][:8]


def test_an_error_message_cannot_break_the_compare_table():
    from evals.extract_eval import compare
    line = compare.table([{"run": "r", "invalid": "4 of 4 calls failed\nfirst: a | b"}]).splitlines()[-1]
    assert "first: a / b" in line and line.count("|") == compare.table([{"run": "r"}]).splitlines()[-1].count("|")


@needs_data
def test_an_id_in_two_top_up_rounds_stops_the_run_before_any_call(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run
    model = EchoModel()
    monkeypatch.setattr(run, "_client", lambda location: model)
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(run, "SETS_DIR", tmp_path / "sets")
    (tmp_path / "sets" / "topup").mkdir(parents=True)
    for v in ("v1", "v2"):                                          # the same notes in two rounds
        (tmp_path / "sets" / "topup" / f"golden_topup_{v}.evalset.json").write_bytes(EVALSET.read_bytes())
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "1", "--set", "topup"])
    with pytest.raises(SystemExit, match="ids must be unique"):
        run.main()
    assert not model.prompts and not (tmp_path / "runs").exists()


@needs_data
def test_an_unknown_vertical_stops_the_run_before_any_call(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run
    model = EchoModel()
    monkeypatch.setattr(run, "_client", lambda location: model)
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(run, "SETS_DIR", tmp_path / "sets")
    (tmp_path / "sets" / "topup").mkdir(parents=True)
    data = json.loads(EVALSET.read_text(encoding="utf-8"))
    data["eval_cases"] = data["eval_cases"][:2]
    data["eval_cases"][1]["session_input"]["state"]["vertical"] = "XX"   # a vertical with no field list
    (tmp_path / "sets" / "topup" / "golden_topup_v1.evalset.json").write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "1", "--set", "topup"])
    with pytest.raises(SystemExit, match="vertical 'XX'"):
        run.main()
    assert not model.prompts and not (tmp_path / "runs").exists()


@needs_data
def test_with_dispositions_the_codes_are_asked_for_scored_and_kept_on_rescore(monkeypatch, tmp_path):
    from evals.agent_eval import judge as judge_mod
    from evals.extract_eval import run
    model = EchoModel()
    monkeypatch.setattr(run, "_client", lambda location: model)
    monkeypatch.setattr(judge_mod, "Judge", FakeJudge)
    monkeypatch.setattr(run, "RUNS", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run", "--model", "stand-in", "--repeats", "1", "--limit", "20",
                                      "--dispositions"])
    run.main()
    out = next(tmp_path.glob("extract-*"))
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    golden = summary["sets"]["golden"]
    assert summary["dispositions"] is True and all("99: Outcome not covered" in p for p in model.prompts)
    assert golden["scores"]["disposition"]["mean"] == 0.0              # nothing discussed: every code a miss
    assert golden["codes_downgraded_per_run"] == 0.0
    detail = golden["disposition_detail"]
    assert detail["key_99"]["right"] == detail["key_real_code"]["right"] == 0 and detail["real_codes_kept"] == 0
    assert "Disposition by the key's code" in (out / "scorecard_golden.md").read_text(encoding="utf-8")

    monkeypatch.setattr(run, "_client", lambda location: pytest.fail("a re-score must not call the model"))
    monkeypatch.setattr(sys, "argv", ["run", "--rescore", str(out)])
    run.main()
    after = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert after["dispositions"] is True and after["sets"]["golden"]["scores"] == golden["scores"]


def test_disposition_detail_splits_by_the_keys_code_and_counts_repeated_evidence():
    from evals.extract_eval.run import detail_line, disposition_detail

    def row(expected, ok, code, evidence, outcome):
        return {"score": {"topics": [{"topic": "T", "expected_code": expected, "code_ok": ok},
                                     {"topic": "U"}]},                     # the key says not discussed: not counted
                "record": {"topics": [{"topic": "T", "status": "discussed", "disposition_code": code,
                                       "evidence": evidence, "outcome_evidence": outcome},
                                      {"topic": "U", "status": "not_discussed", "disposition_code": None}]}}
    rows = [row(99, True, 99, "pool pricing", ""),                          # the fallback, right
            row(99, False, 1, "pool pricing", "wants to buy two"),          # a real code where the key says 99
            row(2, True, 2, "pool pricing", "Pool  PRICING"),               # kept on the topic's evidence again
            row(3, False, 99, "pool pricing", ""),
            {"score": None, "record": None}]                                # a failed call: nothing to count
    d = disposition_detail(rows)
    assert d["key_99"] == {"right": 1, "of": 2, "pct": 50.0}
    assert d["key_real_code"] == {"right": 1, "of": 2, "pct": 50.0}
    assert d["always_99_pct"] == 50.0
    assert d["real_codes_kept"] == 2 and d["kept_on_the_topic_evidence_again"] == 1
    assert "1/2 right where the key says 99" in detail_line(d)
    empty = disposition_detail([])
    assert empty["key_99"]["pct"] is None and empty["always_99_pct"] is None
