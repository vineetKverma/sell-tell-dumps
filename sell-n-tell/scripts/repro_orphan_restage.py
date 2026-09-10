"""AIML-2703 regression suite -- correction, re-stage and commit gates.

Runs the workflow in-process. No server, no Vertex, no credentials:

    uv run python scripts/repro_orphan_restage.py

Originally this drove the REST API over HTTP. The contract-simplification pass
(AIML-2750) removed that API -- ``/api/v1/notes/stage`` and ``/commit`` no
longer exist, and the only network surface is the WebSocket -- so the script
could no longer run at all. It now imports ``notes_workflow`` directly, which is
where those gates actually live.

That is a straight improvement: the gates are pure functions over in-process
state, so testing them needs neither a running app nor a model. The
conversational smoke test cannot cover them at all -- the agent always commits
the record it just staged, never the one it replaced, so the supersede gate can
only be exercised by holding an old session_id deliberately, which is what this
does.

The original hypothesis, from code reading, now fixed and guarded here:

    stage_notes() mints a brand-new session_id on every call, including a
    correction. The record being corrected was left in _STAGED_NOTES -- not
    deleted, not marked superseded, still a valid commit target. So one visit
    with N corrections left N+1 committable drafts, each holding a different
    version of the data. Committing an old draft wrote the PRE-correction
    payload, and because the idempotency guard keys on session_id, the two
    looked like unrelated commits and both succeeded: one visit, two records.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# Load notes_workflow (and the schemas it imports) directly rather than through
# `voice_notes_agent/__init__.py`, which pulls in the ADK agent. The gates are
# plain functions over in-process state and need none of that -- importing the
# package would make this script require ADK, Vertex config and a model name to
# test logic that touches none of them.
_PKG_DIR = Path(__file__).resolve().parents[1] / "app" / "voice_notes_agent"
_pkg = types.ModuleType("_vna")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules["_vna"] = _pkg


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"_vna.{name}", _PKG_DIR / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"_vna.{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


_load("schemas")
wf = _load("notes_workflow")

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")


def topic(name: str, code: int = 8, summary: str = "s") -> dict:
    return {
        "topic": name,
        "disposition_code": code,
        "executive_summary": summary,
        "discussed": True,
    }


def payload(topics: list[dict], summary: str = "Visit summary.") -> dict:
    return {
        "event_type": "Meeting",
        "executive_summary": summary,
        "raw_transcript_backup": "transcript",
        "topics": topics,
    }


def staged_count() -> int:
    return len(wf._STAGED_NOTES)


def committed_ids() -> set[str]:
    return {
        sid
        for sid, rec in wf._STAGED_NOTES.items()
        if rec.get("committed")
    }


def main() -> int:
    # --- the orphan bug: committing a draft a correction replaced -----------
    first = wf.stage_notes(
        payload([topic("Pricing discussion", 2)]), planned_topics=["Pricing discussion"]
    )
    second = wf.stage_notes(
        payload([topic("Pricing discussion", 8)]),
        previous_session_id=first["session_id"],
        planned_topics=["Pricing discussion"],
    )
    check(
        "a correction re-stages under a new session_id",
        second["session_id"] != first["session_id"],
    )

    try:
        wf.commit_notes(first["session_id"], True)
        check("committing the superseded draft is refused", False, "no raise")
    except wf.SupersededRecordError as exc:
        check(
            "committing the superseded draft is refused",
            exc.superseded_by == second["session_id"],
            f"superseded_by={exc.superseded_by}",
        )

    check("the refused commit committed nothing", not committed_ids())

    wf.commit_notes(second["session_id"], True)
    check(
        "the corrected record commits normally",
        committed_ids() == {second["session_id"]},
    )

    # --- retry safety -------------------------------------------------------
    again = wf.commit_notes(second["session_id"], True)
    check("a retry is accepted rather than 404ing", again is not None)
    check(
        "the retry created no second committed record",
        committed_ids() == {second["session_id"]},
    )

    # --- a chain of corrections: only the last is committable ---------------
    a = wf.stage_notes(payload([topic("Pricing discussion", 1)]), planned_topics=["Pricing discussion"])
    b = wf.stage_notes(
        payload([topic("Pricing discussion", 2)]),
        previous_session_id=a["session_id"],
        planned_topics=["Pricing discussion"],
    )
    c = wf.stage_notes(
        payload([topic("Pricing discussion", 8)]),
        previous_session_id=b["session_id"],
        planned_topics=["Pricing discussion"],
    )
    for label, sid in (("first", a["session_id"]), ("middle", b["session_id"])):
        try:
            wf.commit_notes(sid, True)
            check(f"the {label} draft in a chain is refused", False, "no raise")
        except wf.SupersededRecordError:
            check(f"the {label} draft in a chain is refused", True)
    wf.commit_notes(c["session_id"], True)
    check(
        "only the newest draft in the chain commits",
        c["session_id"] in committed_ids() and a["session_id"] not in committed_ids(),
    )

    # --- commit without a valid staged session ------------------------------
    try:
        wf.commit_notes("no-such-session", True)
        check("an unknown session_id raises", False, "no raise")
    except KeyError:
        check("an unknown session_id raises", True)

    # --- coverage gate, and its release on a correction ---------------------
    planned = ["Pricing discussion", "Contract renewal"]
    d = wf.stage_notes(payload([topic("Pricing discussion", 8)]), planned_topics=planned)
    try:
        wf.commit_notes(d["session_id"], True)
        check("an incomplete record is blocked", False, "no raise")
    except wf.IncompleteCoverageError as exc:
        check(
            "an incomplete record is blocked",
            exc.missing_topics == ["Contract renewal"],
            str(exc.missing_topics),
        )
    e = wf.stage_notes(
        payload([topic("Pricing discussion", 8), topic("Contract renewal", 2)]),
        previous_session_id=d["session_id"],
        planned_topics=planned,
    )
    wf.commit_notes(e["session_id"], True)
    check("the correction that adds the topic commits", e["session_id"] in committed_ids())

    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
