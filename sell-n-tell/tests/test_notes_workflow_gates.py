"""AIML-2703 gates: what protects a corrected visit from being saved twice.

Two distinct call patterns, tested separately because they behave differently
and only one of them is what the live app does.

**Live pattern** (``TestLiveCallPattern``) mirrors ``tools.py``: every
``stage_notes`` call in a visit passes the SAME ``session_id``
(``tool_context.session.id``), varying only ``previous_session_id``. Because
``previous_session_id == session_id``, the ``superseded_by`` branch in
``stage_notes`` never fires -- a correction overwrites the staged record in
place. One visit therefore only ever has one committable draft, which is what
actually delivers AIML-2703's guarantee in production. The supersede gate is
not what protects this path.

**Workflow-API pattern** (``TestSupersedeGate``) passes distinct session ids,
as any non-agent caller would. There the supersede marker does fire, and the
gate is what stops a stale draft being committed. This is defence for callers
that are not ``tools.py``.

Neither pattern is reachable from the conversational smoke test: the agent
always commits the record it just staged, so no scripted scenario can hold a
stale id or exercise a second draft.

    uv run pytest tests/ -q

No server, no credentials, no Vertex config. The dependencies still get
installed as normal; the tests just never import the ADK agent (see
conftest.py), so nothing that needs a model or a network connection runs.
"""

from __future__ import annotations

import pytest

from conftest import payload, topic


class TestLiveCallPattern:
    """Same session_id across corrections -- what tools.py actually does."""

    def test_correction_overwrites_in_place(self, workflow):
        sid = "ws-session-1"
        workflow.stage_notes(
            payload([topic("Pricing discussion", 2)]),
            planned_topics=["Pricing discussion"],
            session_id=sid,
        )
        workflow.stage_notes(
            payload([topic("Pricing discussion", 8)]),
            previous_session_id=sid,
            planned_topics=["Pricing discussion"],
            session_id=sid,
        )

        assert list(workflow._STAGED_NOTES) == [sid], (
            "a correction must not leave a second committable draft"
        )
        assert workflow._STAGED_NOTES[sid].get("superseded_by") is None, (
            "superseded_by cannot fire when previous_session_id == session_id"
        )
        topics = workflow._STAGED_NOTES[sid]["payload"]["topics"]
        assert topics[0]["disposition_code"] == 8, "correction did not land"

    def test_correction_count_carries_forward(self, workflow):
        sid = "ws-session-2"
        workflow.stage_notes(
            payload([topic("Pricing discussion", 1)]),
            planned_topics=["Pricing discussion"],
            session_id=sid,
        )
        for code in (2, 8):
            workflow.stage_notes(
                payload([topic("Pricing discussion", code)]),
                previous_session_id=sid,
                planned_topics=["Pricing discussion"],
                session_id=sid,
            )
        assert workflow._STAGED_NOTES[sid]["correction_count"] == 2

    def test_one_visit_commits_once(self, workflow):
        sid = "ws-session-3"
        workflow.stage_notes(
            payload([topic("Pricing discussion", 2)]),
            planned_topics=["Pricing discussion"],
            session_id=sid,
        )
        workflow.stage_notes(
            payload([topic("Pricing discussion", 8)]),
            previous_session_id=sid,
            planned_topics=["Pricing discussion"],
            session_id=sid,
        )
        workflow.commit_notes(sid, True)

        committed = [
            s for s, r in workflow._STAGED_NOTES.items() if r.get("committed")
        ]
        assert committed == [sid], "one visit, one committed record"

    def test_retry_replays_rather_than_404ing(self, workflow):
        sid = "ws-session-4"
        workflow.stage_notes(
            payload([topic("Pricing discussion", 8)]),
            planned_topics=["Pricing discussion"],
            session_id=sid,
        )
        first = workflow.commit_notes(sid, True)
        again = workflow.commit_notes(sid, True)

        assert again is not None, "a retry must not raise"
        assert getattr(again, "session_id", sid) == getattr(
            first, "session_id", sid
        )

    def test_coverage_gate_blocks_then_releases(self, workflow):
        sid = "ws-session-5"
        planned = ["Pricing discussion", "Contract renewal"]
        workflow.stage_notes(
            payload([topic("Pricing discussion", 8)]),
            planned_topics=planned,
            session_id=sid,
        )
        with pytest.raises(workflow.IncompleteCoverageError) as exc:
            workflow.commit_notes(sid, True)
        assert exc.value.missing_topics == ["Contract renewal"]

        workflow.stage_notes(
            payload(
                [topic("Pricing discussion", 8), topic("Contract renewal", 2)]
            ),
            previous_session_id=sid,
            planned_topics=planned,
            session_id=sid,
        )
        workflow.commit_notes(sid, True)
        assert workflow._STAGED_NOTES[sid]["committed"] is True


class TestSupersedeGate:
    """Distinct session ids -- any caller that is not tools.py."""

    def test_superseded_draft_is_refused(self, workflow):
        first = workflow.stage_notes(
            payload([topic("Pricing discussion", 2)]),
            planned_topics=["Pricing discussion"],
        )
        second = workflow.stage_notes(
            payload([topic("Pricing discussion", 8)]),
            previous_session_id=first["session_id"],
            planned_topics=["Pricing discussion"],
        )
        assert first["session_id"] != second["session_id"]

        with pytest.raises(workflow.SupersededRecordError) as exc:
            workflow.commit_notes(first["session_id"], True)
        assert exc.value.superseded_by == second["session_id"]

        assert not [
            s for s, r in workflow._STAGED_NOTES.items() if r.get("committed")
        ], "a refused commit must write nothing"

    def test_only_the_newest_draft_in_a_chain_commits(self, workflow):
        a = workflow.stage_notes(
            payload([topic("Pricing discussion", 1)]),
            planned_topics=["Pricing discussion"],
        )
        b = workflow.stage_notes(
            payload([topic("Pricing discussion", 2)]),
            previous_session_id=a["session_id"],
            planned_topics=["Pricing discussion"],
        )
        c = workflow.stage_notes(
            payload([topic("Pricing discussion", 8)]),
            previous_session_id=b["session_id"],
            planned_topics=["Pricing discussion"],
        )

        for stale in (a, b):
            with pytest.raises(workflow.SupersededRecordError):
                workflow.commit_notes(stale["session_id"], True)

        workflow.commit_notes(c["session_id"], True)
        committed = [
            s for s, r in workflow._STAGED_NOTES.items() if r.get("committed")
        ]
        assert committed == [c["session_id"]]

    def test_unknown_session_raises(self, workflow):
        with pytest.raises(KeyError):
            workflow.commit_notes("no-such-session", True)


def test_an_off_plan_row_does_not_cover_a_planned_topic():
    """The agent adds off-plan subjects as their own rows and leaves undiscussed
    planned topics out. "Plumbing leak" containing "plumbing" must not count
    as the planned Plumbing, or the rep is never asked and it saves with no
    outcome."""
    from conftest import wf
    planned = ["Plumbing", "MF Pools 26"]
    rows = [topic("Plumbing leak"), topic("Pools")]
    assert wf.compute_missing_topics(planned, rows) == ["Plumbing", "MF Pools 26"]
    rows += [topic("plumbing"), topic("MF  Pools 26")]                    # its own label, any case or spacing
    assert wf.compute_missing_topics(planned, rows) == []


def test_the_read_back_after_a_reminder_says_what_the_rep_said():
    """After a reminder the rep says they skipped a planned topic; the agent
    re-stages it with discussed=false. That is the topic's outcome, and it was
    planned -- so not "a new topic ... as no outcome yet"."""
    from conftest import wf
    planned = ["Plumbing", "MF Pools 26"]
    old = payload([topic("MF Pools 26")])
    skipped = dict(topic("Plumbing"), discussed=False, disposition_code=None)
    text = wf.build_change_confirmation(old, payload([topic("MF Pools 26"), skipped]), planned)
    assert "noted that you didn't get to Plumbing" in text
    assert "no outcome yet" not in text and "a new topic" not in text
    discussed = topic("Plumbing", code=2)
    assert "added Plumbing as" in wf.build_change_confirmation(old, payload([topic("MF Pools 26"), discussed]), planned)
    off_plan = topic("Water heaters", code=2)
    assert "added a new topic, Water heaters" in wf.build_change_confirmation(
        old, payload([topic("MF Pools 26"), off_plan]), planned)


def test_a_spacing_difference_is_not_read_back_as_a_removed_and_added_topic():
    from conftest import wf
    old, new = payload([topic("MF Pools 26")]), payload([topic("mf  pools 26")])
    text = wf.build_change_confirmation(old, new, ["MF Pools 26"])
    assert "removed" not in text and "added" not in text


def test_a_correction_to_skipped_is_read_back_as_skipped():
    """The rep gave Plumbing an outcome, then says "actually we didn't get to
    it": the read-back says so, not "changed the outcome to no outcome yet"."""
    from conftest import wf
    old = payload([topic("Plumbing", code=2)])
    new = payload([dict(topic("Plumbing", summary="Ran out of time."), discussed=False, disposition_code=None)])
    text = wf.build_change_confirmation(old, new, ["Plumbing"])
    assert "noted that you didn't get to Plumbing" in text
    assert "no outcome yet" not in text
    assert "updated the summary" not in text          # one change, read back once
    # A real outcome change still reads as one.
    changed = wf.build_change_confirmation(old, payload([topic("Plumbing", code=8)]), ["Plumbing"])
    assert "changed the Plumbing outcome to" in changed

