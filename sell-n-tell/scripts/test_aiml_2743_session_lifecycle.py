"""Automated offline tests for AIML-2807 and AIML-2743 session lifecycle & state resilience.

Validates:
1. turn_guard.cleanup_session purges all 5 module-level dictionaries.
2. notes_workflow.cleanup_session purges _STAGED_NOTES.
3. notes_workflow.prune_stale_staged_notes evicts stale records while preserving active/recent ones.
4. commit_notes preserves committed records in memory at commit time for idempotent retries.
5. Dual-Sync: stage_visit_notes mirrors state into tool_context.state; commit_visit_notes
   rehydrates from tool_context.state across process restarts (empty RAM).
6. commit_visit_notes returns saved commit_result on subsequent retries.
7. WebSocket disconnect cleanup hook executes on disconnect when acquired=True, but NOT
   when connection was rejected (acquired=False).

Usage:
    uv run python scripts/test_aiml_2807_session_lifecycle.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "app"))
sys.path.insert(0, str(_REPO_ROOT))

import main as app_main
from main import (
    _SESSION_SLOTS,
    _SessionSlot,
    websocket_endpoint,
)
from voice_notes_agent import notes_workflow, turn_guard
from voice_notes_agent.tools import commit_visit_notes, stage_visit_notes


class MockWebSocket:
    """Mock WebSocket for offline FastAPI endpoint testing."""

    def __init__(self) -> None:
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.close_reason: str | None = None
        self.sent_messages: list[str] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, text: str) -> None:
        self.sent_messages.append(text)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.closed = True
        self.close_code = code
        self.close_reason = reason


def test_turn_guard_cleanup() -> None:
    """AC: cleanup_session clears all 5 turn_guard dictionaries."""
    session_id = "test-turn-guard-cleanup-1"

    # Seed all 5 dictionaries
    turn_guard._TURN_COUNTS[session_id] = 5
    turn_guard._BASELINES[session_id] = 2
    turn_guard._AWAITING_READBACK[session_id] = True
    turn_guard._NUDGE_SENT[session_id] = True
    turn_guard._AWAITING_TOOL[session_id] = "stage_visit_notes"

    assert session_id in turn_guard._TURN_COUNTS
    assert session_id in turn_guard._BASELINES
    assert session_id in turn_guard._AWAITING_READBACK
    assert session_id in turn_guard._NUDGE_SENT
    assert session_id in turn_guard._AWAITING_TOOL

    # Cleanup
    turn_guard.cleanup_session(session_id)

    assert session_id not in turn_guard._TURN_COUNTS
    assert session_id not in turn_guard._BASELINES
    assert session_id not in turn_guard._AWAITING_READBACK
    assert session_id not in turn_guard._NUDGE_SENT
    assert session_id not in turn_guard._AWAITING_TOOL

    # Safe no-op on non-existent session
    turn_guard.cleanup_session("non-existent-session-id")
    print("PASS: test_turn_guard_cleanup")


def test_notes_workflow_cleanup_and_pruning() -> None:
    """AC: cleanup_session reaps staged notes and prune_stale_staged_notes handles TTL."""
    session_id = "test-notes-cleanup-1"

    payload = {
        "event_type": "Phone Call",
        "executive_summary": "Discussed Q3 pricing and order volume.",
        "topics": [
            {
                "topic": "Pricing",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "Offered 5% discount on bulk order.",
            }
        ],
    }
    notes_workflow.stage_notes(payload=payload, session_id=session_id, planned_topics=["Pricing"])
    assert notes_workflow.get_staged(session_id) is not None

    # Test explicit cleanup
    notes_workflow.cleanup_session(session_id)
    assert notes_workflow.get_staged(session_id) is None

    # Test TTL pruning:
    stale_id = "test-stale-session"
    recent_id = "test-recent-session"

    now = datetime.now(timezone.utc)
    old_time = (now - timedelta(hours=2)).isoformat()
    recent_time = (now - timedelta(minutes=5)).isoformat()

    notes_workflow._STAGED_NOTES[stale_id] = {
        "payload": payload,
        "planned_topics": ["Pricing"],
        "staged_at": old_time,
        "committed": True,
        "committed_at": old_time,
    }
    notes_workflow._STAGED_NOTES[recent_id] = {
        "payload": payload,
        "planned_topics": ["Pricing"],
        "staged_at": recent_time,
        "committed": True,
        "committed_at": recent_time,
    }

    evicted = notes_workflow.prune_stale_staged_notes(max_age_seconds=3600.0)
    assert evicted == 1, f"Expected 1 evicted record, got {evicted}"
    assert notes_workflow.get_staged(stale_id) is None
    assert notes_workflow.get_staged(recent_id) is not None

    # Cleanup recent
    notes_workflow.cleanup_session(recent_id)
    print("PASS: test_notes_workflow_cleanup_and_pruning")


def test_commit_notes_retention_and_idempotent_retry() -> None:
    """AC: commit_notes does NOT delete the record at commit time, allowing retries."""
    session_id = "test-commit-retry-1"

    payload = {
        "event_type": "Phone Call",
        "executive_summary": "Followed up on product trial.",
        "topics": [
            {
                "topic": "Product Demo",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "Trial going well.",
            }
        ],
    }
    notes_workflow.stage_notes(payload=payload, session_id=session_id, planned_topics=["Product Demo"])

    # 1. Commit
    result1 = notes_workflow.commit_notes(session_id, confirmed=True)
    assert result1.session_id == session_id

    # 2. Invariant: Record MUST STILL BE in _STAGED_NOTES at commit time!
    staged_after_commit = notes_workflow.get_staged(session_id)
    assert staged_after_commit is not None, "Record was deleted at commit time!"
    assert staged_after_commit["committed"] is True

    # 3. Idempotent Retry: Calling commit_notes again returns identical result
    result2 = notes_workflow.commit_notes(session_id, confirmed=True)
    assert result2 == result1

    # Clean up after test
    notes_workflow.cleanup_session(session_id)
    print("PASS: test_commit_notes_retention_and_idempotent_retry")


@pytest.mark.asyncio
async def test_tools_dual_sync_and_rehydration_restart() -> None:
    """AC: Dual-Sync stores state in tool_context.state; restart rehydrates and commits."""
    session_id = "test-restart-rehydration-1"

    mock_session = MagicMock()
    mock_session.id = session_id

    tool_context = MagicMock()
    tool_context.session = mock_session
    tool_context.state = {"planned_topics": ["Efficacy"]}

    # 1. Call stage_visit_notes
    stage_res = await stage_visit_notes(
        event_type="Meeting",
        executive_summary="Quarterly review with Dr. Smith.",
        raw_transcript_backup="Quarterly review with Dr. Smith discussing efficacy.",
        topics=[
            {
                "topic": "Efficacy",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "Dr. Smith noted positive patient response.",
            }
        ],
        tool_context=tool_context,
    )
    assert stage_res["status"] == "staged"
    staged_sid = stage_res["session_id"]

    # Verify Dual-Sync persisted full record to tool_context.state
    assert "staged_record" in tool_context.state
    assert (
        tool_context.state["staged_record"]["payload"]["executive_summary"]
        == "Quarterly review with Dr. Smith."
    )

    # 2. Simulate Process Restart: wipe process-local RAM (_STAGED_NOTES and turn_guard)
    notes_workflow._STAGED_NOTES.clear()
    assert notes_workflow.get_staged(staged_sid) is None, "RAM not cleared"

    # Simulate agent delivered readback and rep replied "yes save it"
    turn_guard.record_agent_speech(staged_sid, "Read back summary")
    turn_guard.record_user_turn(staged_sid, "yes save it")

    from app.voice_notes_agent.confirmation import ConfirmationResult

    with patch("voice_notes_agent.confirmation.interpret_async", new_callable=AsyncMock) as mock_interpret:
        mock_interpret.return_value = ConfirmationResult(intent="confirm", reasoning="Confirmed in test")

        # 3. Call commit_visit_notes in the fresh process
        commit_res = await commit_visit_notes(tool_context=tool_context)
        assert commit_res["status"] == "success", f"Commit failed: {commit_res}"
        assert commit_res["session_id"] == staged_sid

        # Verify that RAM was rehydrated and tool_context.state has commit_result
        assert notes_workflow.get_staged(staged_sid) is not None, "Did not rehydrate into RAM"
        assert tool_context.state.get("commit_result") is not None
        assert tool_context.state.get("committed") is True

        # 4. Immediate tool retry on committed session
        retry_res = await commit_visit_notes(tool_context=tool_context)
        assert retry_res["status"] == "success"
        assert retry_res["session_id"] == staged_sid

    # Clean up
    notes_workflow.cleanup_session(staged_sid)
    turn_guard.cleanup_session(staged_sid)
    print("PASS: test_tools_dual_sync_and_rehydration_restart")


@pytest.mark.asyncio
async def test_websocket_disconnect_cleanup_hook() -> None:
    """AC: WebSocket disconnect hook reaps dictionaries if acquired=True, not if acquired=False."""
    session_id = "test-ws-cleanup-hook-1"
    user_id = "test-user-ws"

    ws1 = MockWebSocket()

    async def mock_dictation(ws, uid, sid, planned, campaign):
        # Stage something and set turn_guard state during active call
        turn_guard.record_user_turn(sid, "test turn")
        notes_workflow._STAGED_NOTES[sid] = {"mock": "data"}

    with patch.object(app_main, "_run_dictation_session", side_effect=mock_dictation):
        await websocket_endpoint(ws1, user_id, session_id)

    # After normal completion/disconnect, acquired was True -> state cleaned up!
    assert session_id not in turn_guard._TURN_COUNTS
    assert notes_workflow.get_staged(session_id) is None
    assert session_id not in _SESSION_SLOTS

    # Test rejected concurrent attach: does NOT wipe active session state!
    active_sid = "test-active-held-session"
    turn_guard._TURN_COUNTS[active_sid] = 99
    notes_workflow._STAGED_NOTES[active_sid] = {"keep": "me"}

    # Mock an already-locked slot
    held_slot = _SessionSlot()
    await held_slot.lock.acquire()
    _SESSION_SLOTS[active_sid] = held_slot

    ws_rejected = MockWebSocket()
    await websocket_endpoint(ws_rejected, user_id, active_sid)

    assert ws_rejected.close_code == 4409  # session_busy
    # Invariant: Rejected attach MUST NOT clear active session's state!
    assert turn_guard._TURN_COUNTS.get(active_sid) == 99
    assert notes_workflow.get_staged(active_sid) == {"keep": "me"}

    # Release held lock manually
    held_slot.lock.release()
    _SESSION_SLOTS.pop(active_sid, None)
    turn_guard.cleanup_session(active_sid)
    notes_workflow.cleanup_session(active_sid)
    print("PASS: test_websocket_disconnect_cleanup_hook")


@pytest.mark.asyncio
async def test_multi_stage_corrections_with_midstream_drop_and_reconnection() -> None:
    """AC: Multiple stages/corrections survive midstream drop, reconnect on same session_id, and commit."""
    session_id = "test-multistage-reconnect-1"

    mock_session = MagicMock()
    mock_session.id = session_id

    tool_context = MagicMock()
    tool_context.session = mock_session
    tool_context.state = {"planned_topics": ["Pricing", "Efficacy"]}

    # Stage 1: Initial dictation (Pricing only)
    res1 = await stage_visit_notes(
        event_type="Meeting",
        executive_summary="Discussed pricing with Dr. Smith.",
        raw_transcript_backup="Discussed pricing with Dr. Smith.",
        topics=[
            {
                "topic": "Pricing",
                "discussed": True,
                "disposition_code": 8,
                "executive_summary": "Offered 5% discount.",
            }
        ],
        tool_context=tool_context,
    )
    assert res1["status"] == "staged"
    # Note: Efficacy was planned but not yet addressed
    assert "Efficacy" in (res1.get("missing_topics") or [])
    assert tool_context.state["staged_record"]["payload"]["executive_summary"] == "Discussed pricing with Dr. Smith."

    # Stage 2: Correction / addition (addressed Efficacy + updated discount)
    res2 = await stage_visit_notes(
        event_type="Meeting",
        executive_summary="Discussed pricing and efficacy with Dr. Smith.",
        raw_transcript_backup="Discussed pricing and efficacy with Dr. Smith.",
        topics=[
            {
                "topic": "Pricing",
                "discussed": True,
                "disposition_code": 8,
                "executive_summary": "Offered 10% discount.",  # changed from 5 to 10
            },
            {
                "topic": "Efficacy",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "Positive efficacy results.",
            },
        ],
        tool_context=tool_context,
    )
    assert res2["status"] == "staged"
    assert not res2.get("missing_topics")
    assert tool_context.state["staged_record"]["correction_count"] == 1
    assert tool_context.state["staged_record"]["payload"]["executive_summary"] == "Discussed pricing and efficacy with Dr. Smith."

    # SIMULATE HARD NETWORK DROP / CONTAINER RESTART IN THE MIDDLE
    # In-memory RAM is completely wiped!
    notes_workflow._STAGED_NOTES.clear()
    assert notes_workflow.get_staged(session_id) is None, "RAM was not cleared"

    # CLIENT RECONNECTS WITH THE SAME SESSION ID
    # Server rehydrates from session state
    staged_record = tool_context.state.get("staged_record")
    assert staged_record is not None
    notes_workflow.rehydrate_staged(session_id, staged_record)
    assert notes_workflow.get_staged(session_id) is not None

    # After reconnect, rep speaks on new connection: "Looks good, save it."
    turn_guard.record_agent_speech(session_id, "Summary read back")
    turn_guard.record_user_turn(session_id, "Looks good, save it.")

    from app.voice_notes_agent.confirmation import ConfirmationResult

    with patch("voice_notes_agent.confirmation.interpret_async", new_callable=AsyncMock) as mock_interpret:
        mock_interpret.return_value = ConfirmationResult(intent="confirm", reasoning="Confirmed in test")

        # Commit on reconnected session
        commit_res = await commit_visit_notes(tool_context=tool_context)
    assert commit_res["status"] == "success"
    assert commit_res["executive_summary"] == "Discussed pricing and efficacy with Dr. Smith."
    assert len(commit_res["topics"]) == 2
    assert commit_res["topics"][0]["executive_summary"] == "Offered 10% discount."

    # Cleanup
    notes_workflow.cleanup_session(session_id)
    turn_guard.cleanup_session(session_id)
    print("PASS: test_multi_stage_corrections_with_midstream_drop_and_reconnection")


async def main() -> None:
    print("Running AIML-2807 & AIML-2743 session lifecycle tests...\n")
    test_turn_guard_cleanup()
    test_notes_workflow_cleanup_and_pruning()
    test_commit_notes_retention_and_idempotent_retry()
    await test_tools_dual_sync_and_rehydration_restart()
    await test_websocket_disconnect_cleanup_hook()
    await test_multi_stage_corrections_with_midstream_drop_and_reconnection()
    print("\nALL LIFECYCLE & RESILIENCE TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
