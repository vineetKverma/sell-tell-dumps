"""Quick subset, committed baseline and regression verdicts. No model, no network."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parents[1])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from evals.agent_eval import baseline as bl  # noqa: E402
from evals.agent_eval.cases import EVALSET, Case, dataset_sha256, quick_subset  # noqa: E402

needs_data = pytest.mark.skipif(not EVALSET.exists(), reason="golden eval data not present")


def _case(cid, vertical):
    return Case(id=cid, vertical=vertical, note="n", planned_topics=["t"], event_type="Meeting",
                topics=[], fields={})


def test_quick_subset_is_fixed_and_balanced():
    cases = [_case(f"{v}-{i:03d}", v) for v in ("MH", "HL") for i in (5, 1, 3, 2, 4)]
    picked = quick_subset(cases)
    assert [c.id for c in picked] == ["HL-001", "HL-002", "HL-003", "MH-001", "MH-002", "MH-003"]
    assert quick_subset(list(reversed(cases))) == picked  # order of input does not matter


@needs_data
def test_quick_subset_of_the_golden_set_is_18_cases():
    from evals.agent_eval.cases import load_cases
    picked = quick_subset(load_cases())
    assert len(picked) == 18 and {c.vertical for c in picked} == {"MH", "HS", "HL", "IS", "TR", "IN"}


def _rollup(event, topic, faith, recall, fab):
    acc = lambda r: {"rate": r, "ok": 0, "n": 1}  # noqa: E731
    return {"all": {"event_type": acc(event), "topic_status": acc(topic), "disposition": acc(None),
                    "faithfulness": acc(faith),
                    "fields": {"all": {"recall": recall, "fabrication": fab}, "P1": {"recall": recall}}}}


BASE = {"source_run": "baseline", "full": bl.summarise([_rollup(0.60, 0.49, 0.22, 0.0, 0.0)] * 3)}


def test_baseline_summary_holds_numbers_only():
    s = BASE["full"]
    assert s["event_type"] == {"mean": 60.0, "min": 60.0, "max": 60.0, "stdev": 0.0, "runs": 3,
                               "higher_is_better": True}
    assert "disposition" not in s  # no rate -> not reported, never 0
    text = json.dumps(BASE)
    assert "HL-" not in text and "note" not in text


def test_small_moves_are_noise_and_big_drops_are_regressions():
    same = [_rollup(0.62, 0.47, 0.24, 0.0, 0.0)]
    lines, regressed = bl.compare(same, BASE, "full")
    assert regressed == [] and any("within noise" in l for l in lines)

    worse = [_rollup(0.50, 0.49, 0.22, 0.0, 0.0)]
    _, regressed = bl.compare(worse, BASE, "full")
    assert regressed == ["event_type"]


def test_more_invented_values_is_a_regression_fewer_is_not():
    _, regressed = bl.compare([_rollup(0.60, 0.49, 0.22, 0.30, 0.10)], BASE, "full")
    assert regressed == ["field_invented_rate"]          # invented rate rose 10 points
    _, regressed = bl.compare([_rollup(0.60, 0.70, 0.22, 0.30, 0.0)], BASE, "full")
    assert regressed == []                               # improvements never fail


def test_threshold_follows_the_measured_noise():
    noisy = {"source_run": "b", "full": bl.summarise(
        [_rollup(e, 0.49, 0.22, 0.0, 0.0) for e in (0.50, 0.60, 0.70)])}   # stdev 10 points
    assert bl.threshold_for(noisy["full"]["event_type"]) == pytest.approx(30.0)
    _, regressed = bl.compare([_rollup(0.45, 0.49, 0.22, 0.0, 0.0)], noisy, "full")
    assert regressed == []                    # 15 points down, but within 3 x stdev
    assert bl.threshold_for(BASE["full"]["event_type"]) == 5.0  # never below 5 points


def test_skipped_metrics_are_shown_but_never_fail():
    lines, regressed = bl.compare([_rollup(0.60, 0.49, 0.0, 0.0, 0.0)], BASE, "full", skip=["faithfulness"])
    assert regressed == [] and any("not judged" in l for l in lines)


FAKE_HASH = "golden-set-checksum"


@pytest.fixture(autouse=True)
def _no_golden_file_needed(monkeypatch):
    # final_scores checksums the golden set; these tests are about verdicts, so
    # they use a fixed checksum and run with or without the data (e.g. in CI).
    from evals.agent_eval import run
    monkeypatch.setattr(run, "dataset_sha256", lambda _path=None: FAKE_HASH)


def _final(raw, ref, n=10):
    from evals.agent_eval.run import final_scores
    cases = [_case(f"MH-{i:03d}", "MH") for i in range(n)]
    return final_scores("full", "t", cases, raw, _rollup(0.60, 0.49, 0.22, 0.0, 0.0), ref)


def test_verdicts_pass_regression_and_invalid():
    ok = [{"id": f"MH-{i:03d}", "final": {"x": 1}, "judge": {"faithful": True}} for i in range(10)]
    ref = dict(BASE, dataset_sha256=FAKE_HASH)
    assert _final(ok, ref)["verdict"] == "PASS"

    worse = dict(ref, full=bl.summarise([_rollup(0.90, 0.49, 0.22, 0.0, 0.0)]))
    f = _final(ok, worse)
    assert f["verdict"] == "REGRESSION" and f["regressed"] == ["event_type"]

    broken = [dict(r, final=None, error="ConnectionClosedError") for r in ok[:2]] + ok[2:]
    assert _final(broken, ref)["verdict"] == "INVALID"          # 2 of 10 > 10% errors

    assert _final(ok, dict(ref, dataset_sha256="other"))["verdict"] == "INVALID"
    assert _final(ok, None)["verdict"] == "INVALID"
    f = _final(ok, ref)
    assert {"app_commit", "agent_model", "judge_model", "dataset_sha256"} <= set(f)
    assert "MH-0" not in json.dumps({k: v for k, v in f.items() if k != "connection_errors"})

    partial = _final(ok[:7], ref)                               # stopped part-way
    assert partial["verdict"] == "INVALID" and partial["scored"] == 7


def test_dataset_hash_ignores_line_endings(tmp_path):
    lf, crlf = tmp_path / "lf.json", tmp_path / "crlf.json"
    lf.write_bytes(b'{\n "a": 1\n}\n')
    crlf.write_bytes(b'{\r\n "a": 1\r\n}\r\n')
    assert dataset_sha256(lf) == dataset_sha256(crlf)
    crlf.write_bytes(b'{\r\n "a": 2\r\n}\r\n')
    assert dataset_sha256(lf) != dataset_sha256(crlf)           # content still counts


NOISY = {"source_run": "b", "quick": bl.summarise(
    [_rollup(e, 0.49, 0.22, 0.0, 0.0) for e in (0.40, 0.60, 0.80)])}       # event_type stdev 20 -> limit 60


def test_a_too_noisy_metric_leaves_the_gate_only_when_recorded():
    # Not recorded: still judged (with its wide limit), never silently dropped.
    lines, _ = bl.compare([_rollup(0.10, 0.49, 0.22, 0.0, 0.0)], NOISY, "quick")
    assert not any("too noisy" in l for l in lines)
    # Recorded in the baseline: shown, not judged; a steady metric still fails.
    recorded = dict(NOISY, not_gated={"quick": ["event_type"]})
    lines, regressed = bl.compare([_rollup(0.10, 0.20, 0.22, 0.0, 0.0)], recorded, "quick")
    assert regressed == ["topic_status"]
    assert any("event_type" in l and "too noisy" in l for l in lines)


def test_export_refuses_a_too_noisy_metric_unless_allowed():
    assert bl.too_noisy(NOISY) == ["quick:event_type"]
    with pytest.raises(SystemExit, match="--allow-noisy quick:event_type"):
        bl.not_gated(NOISY)
    assert bl.not_gated(NOISY, ["quick:event_type"]) == {"quick": ["event_type"]}
    assert bl.not_gated(BASE) == {}                             # nothing noisy, nothing dropped


def test_runs_list_what_is_not_in_the_verdict():
    ok = [{"id": f"MH-{i:03d}", "final": {"x": 1}, "judge": {"faithful": True}} for i in range(10)]
    ref = dict(BASE, dataset_sha256=FAKE_HASH, not_gated={"full": ["disposition"]})
    f = _final(ok, ref)
    assert f["verdict"] == "PASS"
    assert "disposition" in f["excluded_from_verdict"]
    assert "too noisy" in f["excluded_from_verdict"]["disposition"]


def test_rescore_skips_a_line_cut_off_mid_write(tmp_path):
    from evals.agent_eval.run import read_run
    p = tmp_path / "run1.jsonl"
    p.write_text('{"id": "MH-000"}\n{"id": "MH-001"}\n{"id": "MH-0', encoding="utf-8")
    assert [r["id"] for r in read_run(p)] == ["MH-000", "MH-001"]
    partial = _final([dict(r, final={"x": 1}) for r in read_run(p)], dict(BASE, dataset_sha256=FAKE_HASH))
    assert partial["verdict"] == "INVALID"                      # the cut-off case never ran
    assert any("never ran" in p for p in partial["problems"])


def test_a_missing_session_endpoint_stops_the_run_but_a_flaky_one_retries():
    httpx = pytest.importorskip("httpx")
    pytest.importorskip("websockets")
    from evals.agent_eval.drive import SessionEndpointError, _session_id

    def resp(status, body):
        return httpx.Response(status, json=body) if isinstance(body, dict) else httpx.Response(status, text=body)

    assert _session_id(resp(200, {"status": "ok", "session_id": "123"})) == "123"
    assert _session_id(resp(200, {"status": "error", "error": "token timeout"})) is None   # retried
    assert _session_id(resp(503, "busy")) is None                                         # retried
    for bad in (resp(404, "Not Found"), resp(200, {"session": "1"}), resp(200, {"status": "ok"})):
        with pytest.raises(SessionEndpointError):
            _session_id(bad)


def test_each_case_is_written_as_it_finishes(tmp_path, monkeypatch):
    import asyncio

    pytest.importorskip("websockets")
    from evals.agent_eval import drive, run

    sink, seen = tmp_path / "run1.jsonl", []

    async def fake_run_case(case, base_url):
        seen.append(len(sink.read_text(encoding="utf-8").splitlines()) if sink.exists() else 0)
        if case.id == "MH-002":
            raise KeyboardInterrupt  # Ctrl-C on the third case
        return {"id": case.id, "final": {"x": 1}, "committed": True}

    monkeypatch.setattr(drive, "run_case", fake_run_case)
    cases = [_case(f"MH-{i:03d}", "MH") for i in range(3)]
    with pytest.raises(KeyboardInterrupt):
        asyncio.run(run._drive(cases, "http://x", lambda _m: None, sink=sink))
    assert seen == [0, 1, 2]                                    # on disk before the next case
    assert [json.loads(l)["id"] for l in sink.read_text(encoding="utf-8").splitlines()] == ["MH-000", "MH-001"]


def test_compare_skips_a_mode_the_baseline_does_not_have():
    lines, regressed = bl.compare([_rollup(0.1, 0.1, 0.1, 0.0, 0.0)], BASE, "quick")
    assert regressed == [] and len(lines) == 4  # header only
