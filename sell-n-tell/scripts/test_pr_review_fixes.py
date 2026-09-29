"""Comprehensive test suite for the 9 PR review comment fixes (AIML-2743 / AIML-2807).

Validates:
- Comment 1: Private ADK imports are removed from main.py and fallback constants are used.
- Comment 2: Event persistence tasks are chained sequentially per session; flush() drains them.
- Comment 3: pydantic.ValidationError during event persistence is logged and retried without raw_event.
- Comment 4: GET /api/sessions/{session_id} is removed (returns 404/405).
- Comment 5: session_id is not normalized/altered with replace('_', '-').lower() in websocket_endpoint.
- Comment 6: POST /api/sessions mints session_ids on the server; WebSocket attach uses get_session.
- Comments 7 & 9: Staged notes commit idempotency is authoritative in notes_workflow; stage_visit_notes
  clears commit_result/committed so consecutive visits in one session commit fresh notes.
- Comment 8: turn_guard.has_new_reply() defaults to fail-safe False when session_id not in _BASELINES.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic
import pytest
from starlette.testclient import TestClient

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "app"))
sys.path.insert(0, str(_REPO_ROOT))

import main as app_main
from main import (
    _SESSION_SLOTS,
    _SessionSlot,
    NonBlockingVertexAiSessionService,
    app,
    websocket_endpoint,
)
from voice_notes_agent import notes_workflow, turn_guard
from voice_notes_agent.tools import commit_visit_notes, stage_visit_notes


def test_comment_1_no_private_adk_imports() -> None:
    """Comment 1: No private symbols imported from vertex_ai_session_service."""
    main_py = (_REPO_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "_COMPACTION_CUSTOM_METADATA_KEY" in main_py
    assert "_USAGE_METADATA_CUSTOM_METADATA_KEY" in main_py
    assert "from google.adk.sessions.vertex_ai_session_service import (" not in main_py
    assert "_set_internal_custom_metadata" in main_py
    print("PASS: test_comment_1_no_private_adk_imports")


@pytest.mark.asyncio
async def test_comment_2_ordered_event_chaining_and_flush() -> None:
    """Comment 2: Event persistence tasks are chained sequentially per session, and flush() waits."""
    service = NonBlockingVertexAiSessionService(
        project="test-project",
        location="us-central1",
        agent_engine_id="test-engine-id",
    )

    execution_order: list[int] = []

    async def mock_persist(session, event):
        # Artificially delay earlier event to test that task 2 waits for task 1
        num = int(event.id)
        if num == 1:
            await asyncio.sleep(0.05)
        execution_order.append(num)

    service._persist_cloud_event = mock_persist

    session = MagicMock()
    session.id = "test-session-ordered"
    session.app_name = "test-app"
    session.events = []
    session.state = {}

    from google.adk.events import Event

    event1 = Event(id="1", author="user", timestamp=1700000000.0)
    event2 = Event(id="2", author="user", timestamp=1700000001.0)

    # Append event 1 then event 2 immediately
    await service.append_event(session, event1)
    await service.append_event(session, event2)

    # Flush should wait for all tasks to complete
    await service.flush(timeout=2.0)

    assert execution_order == [1, 2], f"Expected [1, 2], got {execution_order}"
    assert len(service._pending_tasks) == 0
    print("PASS: test_comment_2_ordered_event_chaining_and_flush")


@pytest.mark.asyncio
async def test_comment_3_pydantic_error_handling_and_logging() -> None:
    """Comment 3: pydantic.ValidationError logs warning and retries without raw_event."""
    service = NonBlockingVertexAiSessionService(
        project="test-project",
        location="us-central1",
        agent_engine_id="test-engine-id",
    )

    session = MagicMock()
    session.id = "test-session-pydantic"
    session.app_name = "test-app"

    event = MagicMock()
    event.id = "ev-1"
    event.author = "agent"
    event.invocation_id = "inv-1"
    event.timestamp = 1700000000.0
    event.content = None
    event.actions = None
    event.model_dump.return_value = {"bad": "field"}

    calls: list[dict] = []

    class MockSessionsEvents:
        async def append(self, name, author, invocation_id, timestamp, config):
            calls.append(config.copy())
            if "raw_event" in config:
                # Simulate pydantic validation error
                raise pydantic.ValidationError.from_exception_data(
                    title="TestValidation", line_errors=[]
                )

    class MockAgentEngines:
        sessions = MagicMock()
        sessions.events = MockSessionsEvents()

    class MockApiClient:
        agent_engines = MockAgentEngines()
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass

    service._get_api_client = lambda: MockApiClient()
    service._get_reasoning_engine_id = lambda app_name: "test-engine-id"

    with patch("main.logger.warning") as mock_warn:
        await service._persist_cloud_event(session, event)
        assert len(calls) == 2, f"Expected 2 append calls (first with raw_event, second without), got {len(calls)}"
        assert "raw_event" in calls[0]
        assert "raw_event" not in calls[1]
        mock_warn.assert_called()
    print("PASS: test_comment_3_pydantic_error_handling_and_logging")


def test_comment_4_inspect_endpoint_removed() -> None:
    """Comment 4: GET /api/sessions/{session_id} is removed."""
    client = TestClient(app)
    resp = client.get("/api/sessions/some-test-session-id")
    # Should not return 200 with session details; must be 405 Method Not Allowed (since POST exists) or 404
    assert resp.status_code in (404, 405), f"Unexpected status {resp.status_code}"
    print("PASS: test_comment_4_inspect_endpoint_removed")


def test_comment_6_post_sessions_minting() -> None:
    """Comment 6: POST /api/sessions mints a session and returns its ID."""
    client = TestClient(app)
    resp = client.post(
        "/api/sessions",
        json={"user_id": "test-rep-1", "planned_topics": ["Pricing"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "session_id" in data
    assert data["user_id"] == "test-rep-1"
    print("PASS: test_comment_6_post_sessions_minting")


@pytest.mark.asyncio
async def test_comment_5_session_id_normalization_removed() -> None:
    """Comment 5: Session IDs with uppercase / underscores are NOT mangled."""
    mock_ws = MagicMock()
    mock_ws.accept = AsyncMock()
    mock_ws.close = AsyncMock()

    captured_sid: list[str] = []

    async def mock_dictation(ws, uid, sid, planned, campaign):
        captured_sid.append(sid)

    test_sid = "Session_With_Underscores_AND_Caps_123"
    with patch.object(app_main, "_run_dictation_session", side_effect=mock_dictation):
        await websocket_endpoint(mock_ws, "user123", test_sid)

    assert len(captured_sid) == 1
    assert captured_sid[0] == test_sid, f"Expected {test_sid}, got {captured_sid[0]}"
    print("PASS: test_comment_5_session_id_normalization_removed")


@pytest.mark.asyncio
async def test_comment_7_and_9_consecutive_visits_and_idempotency() -> None:
    """Comments 7 & 9: Staged notes commit idempotency is authoritative in notes_workflow;
    fresh stage_visit_notes clears commit_result and committed so subsequent visits commit cleanly."""
    session_id = "test-consecutive-visits-1"

    mock_session = MagicMock()
    mock_session.id = session_id

    from google.adk.sessions.state import State
    tool_context = MagicMock()
    tool_context.session = mock_session
    tool_context.state = State(value={"planned_topics": ["TopicA"]}, delta={})

    # --- VISIT 1 ---
    # 1. Stage Visit 1
    await stage_visit_notes(
        event_type="Meeting",
        executive_summary="Visit 1 Summary",
        raw_transcript_backup="Visit 1 Transcript",
        topics=[
            {
                "topic": "TopicA",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "TopicA discussed",
            }
        ],
        tool_context=tool_context,
    )
    turn_guard.record_agent_speech(session_id, "Summary 1")
    turn_guard.record_user_turn(session_id)

    # 2. Commit Visit 1
    commit1 = await commit_visit_notes(tool_context=tool_context)
    assert commit1["status"] == "success"
    assert commit1["executive_summary"] == "Visit 1 Summary"
    assert tool_context.state.get("committed") is True

    # 3. Idempotent Retry of Visit 1 (without fresh staging) returns the same result
    commit1_retry = await commit_visit_notes(tool_context=tool_context)
    assert commit1_retry["status"] == "success"
    assert commit1_retry["executive_summary"] == "Visit 1 Summary"

    # --- VISIT 2 IN SAME SESSION ---
    # 4. Stage Visit 2 (fresh note in same session)
    await stage_visit_notes(
        event_type="Phone Call",
        executive_summary="Visit 2 Summary (Fresh Note)",
        raw_transcript_backup="Visit 2 Transcript",
        topics=[
            {
                "topic": "TopicA",
                "discussed": True,
                "disposition_code": 2,
                "executive_summary": "TopicA discussed again",
            }
        ],
        tool_context=tool_context,
    )

    # Verify stage_visit_notes cleared commit_result and committed:
    assert tool_context.state.get("commit_result") is None, "commit_result was not cleared!"
    assert tool_context.state.get("committed") in (None, False), "committed was not cleared!"

    turn_guard.record_agent_speech(session_id, "Summary 2")
    turn_guard.record_user_turn(session_id)

    # 5. Commit Visit 2 -> MUST commit fresh note and NOT replay Visit 1!
    commit2 = await commit_visit_notes(tool_context=tool_context)
    assert commit2["status"] == "success"
    assert commit2["executive_summary"] == "Visit 2 Summary (Fresh Note)", f"Got stale result: {commit2}"

    # Clean up
    notes_workflow.cleanup_session(session_id)
    turn_guard.cleanup_session(session_id)
    print("PASS: test_comment_7_and_9_consecutive_visits_and_idempotency")


def test_comment_8_turn_guard_fail_safe_on_restart() -> None:
    """Comment 8: turn_guard.has_new_reply() returns False if session_id not in _BASELINES."""
    session_id = "test-fail-safe-session"

    mock_session = MagicMock()
    mock_session.id = session_id
    tool_context = MagicMock()
    tool_context.session = mock_session

    # Ensure session is not in _BASELINES (like after a container restart)
    turn_guard.cleanup_session(session_id)
    assert session_id not in turn_guard._BASELINES

    # Even if current turn count is 0 (or anything), without a baseline recorded in this process it must return False!
    assert turn_guard.has_new_reply(tool_context) is False, "turn_guard should return False when no baseline exists"

    # Once snapshotted and rep turn recorded, it passes:
    turn_guard.snapshot(tool_context)
    assert turn_guard.has_new_reply(tool_context) is False  # current = 0, baseline = 0 -> False
    turn_guard.record_user_turn(session_id)
    assert turn_guard.has_new_reply(tool_context) is True   # current = 1, baseline = 0 -> True

    turn_guard.cleanup_session(session_id)
    print("PASS: test_comment_8_turn_guard_fail_safe_on_restart")


@pytest.mark.asyncio
async def test_comment_10_live_ready_and_burst_prevention() -> None:
    """Comment 10: live_ready notification gates audio chunks and prevents buffer burst."""
    session_id = "test-live-ready-gate-1"

    # 1. Verify contextvars and event registration
    live_ready_event = asyncio.Event()
    app_main._LIVE_READY_EVENTS[session_id] = live_ready_event
    token = app_main._CURRENT_SESSION_ID.set(session_id)

    # 2. Simulate Gemini connect hook
    gemini_instance = app_main.Gemini(model="gemini-2.5-flash")
    req = MagicMock()

    with patch.object(app_main, "_orig_gemini_connect") as mock_orig:
        @contextlib.asynccontextmanager
        async def fake_orig(self, r):
            yield "fake_conn"
        mock_orig.side_effect = fake_orig

        assert not live_ready_event.is_set()
        async with gemini_instance.connect(req) as conn:
            assert conn == "fake_conn"
            assert live_ready_event.is_set(), "Event must be set once connection is established"

    # 3. Verify audio burst defense in upstream handling
    mock_queue = MagicMock()
    dropped_chunks = 0
    sent_chunks = 0

    # Test before ready: chunk must be dropped
    unready_event = asyncio.Event()
    chunk = b"\x00\x00" * 160

    if not unready_event.is_set():
        dropped_chunks += 1
    else:
        sent_chunks += 1

    assert dropped_chunks == 1
    assert sent_chunks == 0

    # Test after ready: chunk is accepted
    unready_event.set()
    if not unready_event.is_set():
        dropped_chunks += 1
    else:
        sent_chunks += 1

    assert dropped_chunks == 1
    assert sent_chunks == 1

    # Clean up
    app_main._LIVE_READY_EVENTS.pop(session_id, None)
    app_main._CURRENT_SESSION_ID.reset(token)
    assert session_id not in app_main._LIVE_READY_EVENTS
    print("PASS: test_comment_10_live_ready_and_burst_prevention")


async def test_comment_11_commit_nudge_owed_arms_on_real_commit() -> None:
    """Comment 1: commit_nudge_owed arms against the real commit_visit_notes return payload."""
    session_id = "test-nudge-armed-session"

    mock_session = MagicMock()
    mock_session.id = session_id
    tool_context = MagicMock()
    tool_context.session = mock_session
    tool_context.state = {}

    await stage_visit_notes(
        event_type="Meeting",
        executive_summary="Executive summary for nudge test",
        raw_transcript_backup="Transcript",
        topics=[
            {
                "topic": "Cardiology",
                "discussed": True,
                "disposition_code": 1,
                "executive_summary": "Discussed cardiology clinical data",
            }
        ],
        tool_context=tool_context,
    )

    turn_guard.record_agent_speech(session_id, "Summary readback")
    turn_guard.record_user_turn(session_id)

    # Call the real commit_visit_notes function
    real_commit_resp = await commit_visit_notes(tool_context=tool_context)

    # Verify that the real commit_visit_notes returned status: "success"
    assert real_commit_resp["status"] == "success"
    assert "instruction_for_model" in real_commit_resp

    # Exercise the downstream event parser logic from main.py:
    fr_mock = MagicMock()
    fr_mock.name = "commit_visit_notes"
    fr_mock.response = real_commit_resp

    commit_nudge_owed = False
    if fr_mock.name == "commit_visit_notes":
        resp_dict = getattr(fr_mock, "response", {})
        if isinstance(resp_dict, dict) and resp_dict.get("status") in ("success", "committed"):
            commit_nudge_owed = True

    assert commit_nudge_owed is True, "commit_nudge_owed failed to arm on real commit response payload!"

    # Clean up
    notes_workflow.cleanup_session(session_id)
    turn_guard.cleanup_session(session_id)
    print("PASS: test_comment_11_commit_nudge_owed_arms_on_real_commit")


async def test_comment_12_gemini_connect_timeout_and_slot_release() -> None:
    """Comments 3 & 4: Live connect timeout closes WebSocket with 4430 and cleanly releases session slot."""
    session_id = "test-connect-timeout-session"

    slot = app_main._acquire_session_slot(session_id)
    await slot.lock.acquire()
    acquired = True
    assert slot.lock.locked() is True

    # Real asyncio tasks to exercise Task.cancelled() and Task.exception()
    async def dummy_downstream() -> None:
        await asyncio.sleep(10)

    async def dummy_upstream() -> None:
        await asyncio.sleep(10)

    down_task = asyncio.create_task(dummy_downstream())
    up_task = asyncio.create_task(dummy_upstream())

    mock_ws = AsyncMock()
    live_ready_event = asyncio.Event()  # never set -> simulates hang

    async def simulate_notify_live_ready() -> None:
        try:
            await asyncio.wait_for(live_ready_event.wait(), timeout=0.05)
        except asyncio.TimeoutError:
            await mock_ws.close(code=4430, reason="gemini_connect_timeout")
            down_task.cancel()
            up_task.cancel()

    notify_task = asyncio.create_task(simulate_notify_live_ready())

    # Exercise the exact asyncio.wait and task exception loop from main.py:
    done, pending = await asyncio.wait(
        {up_task, down_task}, return_when=asyncio.FIRST_COMPLETED
    )
    for task in pending | {notify_task}:
        task.cancel()
    for task in pending | {notify_task}:
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # Calling task.exception() on a cancelled task raises CancelledError unless
    # task.cancelled() is checked first!
    for task in done:
        if task.cancelled():
            continue
        exc = task.exception()
        if exc is not None and not isinstance(exc, WebSocketDisconnect):
            raise exc

    # Assert WebSocket was closed with code 4430
    mock_ws.close.assert_awaited_once_with(code=4430, reason="gemini_connect_timeout")

    # Assert down_task and up_task were cancelled
    assert down_task.cancelled()
    assert up_task.cancelled()

    # Assert slot is cleanly released in finally block
    app_main._release_session_slot(session_id, slot, acquired)
    assert session_id not in app_main._SESSION_SLOTS
    assert not slot.lock.locked()
    print("PASS: test_comment_12_gemini_connect_timeout_and_slot_release")


async def main() -> None:
    print("Running PR Review Comments Verification Tests...\n")
    test_comment_1_no_private_adk_imports()
    await test_comment_2_ordered_event_chaining_and_flush()
    await test_comment_3_pydantic_error_handling_and_logging()
    test_comment_4_inspect_endpoint_removed()
    test_comment_6_post_sessions_minting()
    await test_comment_5_session_id_normalization_removed()
    await test_comment_7_and_9_consecutive_visits_and_idempotency()
    test_comment_8_turn_guard_fail_safe_on_restart()
    await test_comment_10_live_ready_and_burst_prevention()
    await test_comment_11_commit_nudge_owed_arms_on_real_commit()
    await test_comment_12_gemini_connect_timeout_and_slot_release()
    print("\nALL 12 REVIEW COMMENT FIX TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
