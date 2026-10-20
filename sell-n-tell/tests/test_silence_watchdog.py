"""Unit and integration tests for SilenceWatchdog.

Tests timeout progression, consecutive prompts, speech reset, barge-in
cancellation, timeout recovery, and clean WebSocket termination.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.voice_notes_agent import notes_workflow
from app.voice_notes_agent.silence_watchdog import SilenceWatchdog


@pytest.mark.asyncio
class TestSilenceWatchdog:
    """Test suite for SilenceWatchdog state machine."""

    @pytest.fixture(autouse=True)
    def setup_watchdog(self):
        self.session_id = "test-session-silence-123"
        self.timeout_s = 0.05
        self.settle_delay_s = 0.02
        self.goodbye_grace_s = 0.05
        self.agent_turn_timeout_s = 0.1
        self.max_prompts = 3
        self.watchdog = SilenceWatchdog(
            session_id=self.session_id,
            silence_timeout_s=self.timeout_s,
            max_silence_prompts=self.max_prompts,
            settle_delay_s=self.settle_delay_s,
            goodbye_grace_s=self.goodbye_grace_s,
            agent_turn_timeout_s=self.agent_turn_timeout_s,
        )
        self.mock_queue = MagicMock()
        self.mock_queue.send_content = MagicMock()
        self.mock_ws = AsyncMock()
        self.mock_ws.close = AsyncMock()

    async def test_initial_silence_triggers_nudge(self):
        """Turn 0: silence for timeout_s triggers prompt #1."""
        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )

        await asyncio.sleep(self.timeout_s + self.settle_delay_s + 0.05)

        assert self.watchdog.consecutive_silence_count == 1
        assert self.mock_queue.send_content.called
        sent_content = self.mock_queue.send_content.call_args[0][0]
        sent_text = sent_content.parts[0].text
        assert "ready to begin dictating" in sent_text

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_user_speech_resets_silence_count(self):
        """User speech resets consecutive silence count to 0."""
        self.watchdog.consecutive_silence_count = 2
        self.watchdog.on_user_speech()
        assert self.watchdog.consecutive_silence_count == 0
        assert self.watchdog.user_spoke_event.is_set()

    async def test_full_progression_to_session_close(self):
        """3 consecutive silences lead to goodbye and websocket.close(1000)."""
        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )

        # Prompt 1
        await asyncio.sleep(self.timeout_s + self.settle_delay_s + 0.05)
        self.watchdog.on_agent_turn_complete()

        # Prompt 2
        await asyncio.sleep(self.timeout_s + self.settle_delay_s + 0.05)
        self.watchdog.on_agent_turn_complete()

        # Prompt 3 (Goodbye)
        await asyncio.sleep(self.timeout_s + self.settle_delay_s + 0.05)
        self.watchdog.on_agent_turn_complete()

        # Grace period for goodbye audio playback
        await asyncio.sleep(self.goodbye_grace_s + 0.05)

        assert self.watchdog.consecutive_silence_count == self.max_prompts
        assert self.watchdog.is_closed
        self.mock_ws.close.assert_called_once_with(
            code=1000, reason="inactivity_timeout"
        )
        await task

    async def test_barge_in_during_provocation_prevents_close(self):
        """Speech during goodbye resets count and prevents websocket closure."""
        self.watchdog.consecutive_silence_count = 2
        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )

        # Wait for timeout + settle delay to reach attempt #3
        await asyncio.sleep(self.timeout_s + self.settle_delay_s + 0.05)
        assert self.watchdog.consecutive_silence_count == self.max_prompts

        # While agent is delivering goodbye, user barges in
        self.watchdog.on_user_speech()
        assert self.watchdog.consecutive_silence_count == 0

        # Wait past grace period
        await asyncio.sleep(self.goodbye_grace_s + 0.05)

        self.mock_ws.close.assert_not_called()
        assert not self.watchdog.is_closed

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_notes_committed_halts_watchdog(self):
        """Notes committed halts monitoring loop immediately."""
        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )

        self.watchdog.on_notes_committed()
        assert self.watchdog.is_committed

        await asyncio.sleep(0.05)
        assert task.done()
        await task

    async def test_staged_notes_prompt_content(self):
        """When notes are staged, prompt reminds user to confirm notes."""
        notes_workflow._STAGED_NOTES[self.session_id] = {
            "record": {
                "visit_notes": {
                    "event_type": "Phone",
                    "executive_summary": "Test summary",
                    "topics": [],
                }
            }
        }
        try:
            nudge_1 = self.watchdog.build_nudge_prompt(count=1, is_final=False)
            assert nudge_1.startswith("(automated check-in)")
            assert "waiting for their confirmation" in nudge_1

            nudge_2 = self.watchdog.build_nudge_prompt(count=2, is_final=False)
            assert nudge_2.startswith("(automated check-in)")
            assert "save the staged notes" in nudge_2

            final_prompt = self.watchdog.build_nudge_prompt(
                count=3, is_final=True
            )
            assert final_prompt.startswith("(automated check-in)")
            assert "closing this session due to inactivity" in final_prompt
        finally:
            notes_workflow._STAGED_NOTES.pop(self.session_id, None)

    async def test_unstaged_notes_prompt_content(self):
        """When notes are not staged, prompt asks user if ready to dictate."""
        nudge_1 = self.watchdog.build_nudge_prompt(count=1, is_final=False)
        assert nudge_1.startswith("(automated check-in)")
        assert "ready to begin dictating" in nudge_1

        nudge_2 = self.watchdog.build_nudge_prompt(count=2, is_final=False)
        assert nudge_2.startswith("(automated check-in)")
        assert "asking if they can hear you" in nudge_2

        final_prompt = self.watchdog.build_nudge_prompt(count=3, is_final=True)
        assert final_prompt.startswith("(automated check-in)")
        assert "closing this session due to inactivity" in final_prompt

    async def test_agent_speech_resets_silence_timer_after_completion(self):
        """When agent finishes speaking, watchdog gives full timeout to user."""
        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )

        self.watchdog.on_agent_turn_start()
        await asyncio.sleep(0.12)
        assert self.watchdog.consecutive_silence_count == 0
        self.mock_queue.send_content.assert_not_called()

        self.watchdog.on_agent_turn_complete()
        await asyncio.sleep(0.02)
        assert self.watchdog.consecutive_silence_count == 0
        self.mock_queue.send_content.assert_not_called()

        expected_wait = (
            self.watchdog.silence_timeout_s
            + self.watchdog.settle_delay_s
            + 0.05
        )
        await asyncio.sleep(expected_wait)
        assert self.watchdog.consecutive_silence_count == 1
        self.mock_queue.send_content.assert_called_once()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_missing_turn_complete_recovers_via_timeout(self):
        """If turn_complete never fires, agent turn timeout recovers cleanly."""
        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )

        # Trigger prompt #1
        await asyncio.sleep(self.timeout_s + self.settle_delay_s + 0.03)
        assert self.watchdog.consecutive_silence_count == 1
        assert self.watchdog.is_agent_turn

        # Lengthen silence timeout so prompt #2 does not immediately race with timeout recovery
        self.watchdog.silence_timeout_s = 1.0

        # NEVER call on_agent_turn_complete. Wait for agent_turn_timeout_s (0.1s)
        await asyncio.sleep(self.agent_turn_timeout_s + 0.05)
        # Watchdog must recover from agent turn!
        assert not self.watchdog.is_agent_turn

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_slow_tool_call_does_not_timeout_or_nudge(self):
        """Tool call execution extending past timeout does not fire a nudge."""
        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )

        # Tool execution begins (e.g. stage_visit_notes)
        self.watchdog.on_tool_execution_start()
        assert self.watchdog.is_tool_executing

        # Wait longer than agent_turn_timeout_s and silence_timeout_s
        await asyncio.sleep(self.agent_turn_timeout_s + 0.1)

        # Watchdog must NOT time out or fire a nudge while tool is running
        assert self.watchdog.is_tool_executing
        assert self.watchdog.consecutive_silence_count == 0
        self.mock_queue.send_content.assert_not_called()

        # Tool execution completes
        self.watchdog.on_tool_execution_complete()
        assert not self.watchdog.is_tool_executing

        # Now agent turn finishes
        self.watchdog.on_agent_turn_complete()

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_agent_speech_during_settle_delay_skips_prompt_and_preserves_count(
        self,
    ):
        """If agent begins turn during settle delay, prompt is skipped and count stays 0."""
        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )

        # Wait until silence timeout expires and settle delay begins
        await asyncio.sleep(self.timeout_s + 0.01)

        # Agent starts speaking during settle_delay_s (before settle delay finishes)
        self.watchdog.on_agent_turn_start()

        # Let settle delay elapse
        await asyncio.sleep(self.settle_delay_s + 0.02)

        # Prompt must be skipped!
        self.mock_queue.send_content.assert_not_called()
        assert self.watchdog.consecutive_silence_count == 0

        # Agent turn finishes
        self.watchdog.on_agent_turn_complete()

        # Now wait for the full silence timeout + settle delay again
        await asyncio.sleep(self.timeout_s + self.settle_delay_s + 0.05)

        # Next prompt must be #1, NOT #2!
        assert self.watchdog.consecutive_silence_count == 1
        self.mock_queue.send_content.assert_called_once()
        sent_content = self.mock_queue.send_content.call_args[0][0]
        sent_text = sent_content.parts[0].text
        assert "ready to begin" in sent_text
        assert "still silent" not in sent_text

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_tool_execution_ceiling_releases_hold_and_resumes_watchdog(
        self,
    ):
        """Tool execution exceeding ceiling releases hold and watchdog recovers."""
        self.watchdog.tool_execution_timeout_s = 0.06
        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )

        self.watchdog.on_tool_execution_start()
        assert self.watchdog.is_tool_executing

        # Wait longer than tool_execution_timeout_s (0.06s) + agent_turn_timeout_s (0.1s)
        await asyncio.sleep(0.06 + self.agent_turn_timeout_s + 0.05)

        # Watchdog must release tool hold and resume monitoring!
        assert not self.watchdog.is_tool_executing

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_watchdog_exception_retries_and_keeps_session_open(
        self, monkeypatch
    ):
        """Unexpected exception in watchdog run loop retries and keeps websocket open."""
        # Patch sleep to avoid 1s backoff per retry
        orig_sleep = asyncio.sleep

        async def fast_sleep(delay, *args, **kwargs):
            if delay >= 1.0:
                return await orig_sleep(0.01)
            return await orig_sleep(delay, *args, **kwargs)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        fail_count = 0

        async def _failing_wait():
            nonlocal fail_count
            fail_count += 1
            raise RuntimeError("Simulated network failure")

        self.watchdog._wait_for_next_cycle = _failing_wait

        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )
        await asyncio.wait_for(task, timeout=1.0)

        # After max_consecutive_errors (3), loop exits cleanly without closing websocket
        assert fail_count == self.watchdog.max_consecutive_errors
        assert not self.watchdog.is_closed
        self.mock_ws.close.assert_not_called()

    async def test_vad_activity_during_settle_delay_aborts_nudge(self):
        """VAD voice detection during settle delay window cancels prompt injection."""
        self.watchdog.settle_delay_s = 0.05

        async def _trigger_vad():
            await asyncio.sleep(0.01)
            self.watchdog.on_voice_detected(grace_seconds=5.0)

        vad_task = asyncio.create_task(_trigger_vad())
        prompt_sent = await self.watchdog._handle_prompt_cycle(
            self.mock_queue, self.mock_ws
        )
        await vad_task

        assert prompt_sent is False
        assert self.watchdog.consecutive_silence_count == 0
        self.mock_queue.send_content.assert_not_called()

    async def test_prompt_cycle_reflects_notes_staged_during_settle_delay(
        self, monkeypatch
    ):
        """Prompt text must reflect staged notes even if notes were staged during the settle delay."""
        self.watchdog.settle_delay_s = 0.05
        # Initially notes are not staged
        monkeypatch.setattr(
            notes_workflow, "get_staged", lambda session_id: None
        )

        async def _stage_during_delay():
            await asyncio.sleep(0.01)
            # Staged notes arrive during settle delay
            monkeypatch.setattr(
                notes_workflow,
                "get_staged",
                lambda session_id: {
                    "status": "staged",
                    "event_type": "On-site visit",
                },
            )

        stage_task = asyncio.create_task(_stage_during_delay())
        should_stop = await self.watchdog._handle_prompt_cycle(
            self.mock_queue, self.mock_ws
        )
        await stage_task

        assert should_stop is False
        assert self.watchdog.consecutive_silence_count == 1
        # The prompt injected must be the staged prompt, asking for confirmation to save
        self.mock_queue.send_content.assert_called_once()
        content = self.mock_queue.send_content.call_args[0][0]
        sent_text = content.parts[0].text
        assert "waiting for their confirmation to save" in sent_text
        assert "begin dictating" not in sent_text

    async def test_watchdog_error_counter_resets_on_healthy_iteration(
        self, monkeypatch
    ):
        """Transient errors interleaved with healthy cycles reset consecutive_errors."""
        orig_sleep = asyncio.sleep

        async def fast_sleep(delay, *args, **kwargs):
            if delay >= 1.0:
                return await orig_sleep(0.01)
            return await orig_sleep(delay, *args, **kwargs)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        call_idx = 0
        min_cycles = 6

        async def _alternating_wait():
            nonlocal call_idx
            call_idx += 1
            # Calls 1, 3, 5 raise transient errors; calls 2, 4 are healthy (return False)
            if call_idx in (1, 3, 5):
                raise RuntimeError(f"Transient error {call_idx}")
            if call_idx >= min_cycles:
                # Terminate watchdog loop after verifying recovery
                self.watchdog.is_committed = True
                return False
            # Healthy iteration (no prompt needed)
            return False

        self.watchdog._wait_for_next_cycle = _alternating_wait

        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )
        await asyncio.wait_for(task, timeout=1.0)

        # 3 non-consecutive errors occurred, but watchdog never reached max_consecutive_errors (3 in a row)
        assert call_idx >= min_cycles
        assert not self.watchdog.is_closed
        self.mock_ws.close.assert_not_called()

    async def test_watchdog_disables_after_consecutive_prompt_cycle_errors(
        self, monkeypatch
    ):
        """Watchdog disables itself without closing session after 3 consecutive prompt cycle errors."""
        orig_sleep = asyncio.sleep

        async def fast_sleep(delay, *args, **kwargs):
            if delay >= 1.0:
                return await orig_sleep(0.01)
            return await orig_sleep(delay, *args, **kwargs)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        fail_count = 0

        async def _failing_prompt_cycle(live_request_queue, websocket):
            nonlocal fail_count
            fail_count += 1
            raise RuntimeError("Simulated prompt cycle failure")

        self.watchdog._handle_prompt_cycle = _failing_prompt_cycle
        self.watchdog._wait_for_next_cycle = AsyncMock(return_value=True)

        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )
        await asyncio.wait_for(task, timeout=1.0)

        # Watchdog stopped running after 3 consecutive failures
        assert task.done()
        assert fail_count == self.watchdog.max_consecutive_errors
        assert not self.watchdog.is_closed
        self.mock_ws.close.assert_not_called()

    async def test_watchdog_disables_after_consecutive_send_content_errors(
        self, monkeypatch
    ):
        """Watchdog disables itself when real _handle_prompt_cycle experiences persistent send_content failures."""
        orig_sleep = asyncio.sleep

        async def fast_sleep(delay, *args, **kwargs):
            if delay >= 1.0:
                return await orig_sleep(0.01)
            return await orig_sleep(delay, *args, **kwargs)

        monkeypatch.setattr(asyncio, "sleep", fast_sleep)

        self.mock_queue.send_content.side_effect = RuntimeError(
            "Persistent queue send failure"
        )
        self.watchdog._wait_for_next_cycle = AsyncMock(return_value=True)

        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )
        await asyncio.wait_for(task, timeout=1.0)

        # Real _handle_prompt_cycle reset agent turn flags on failure and tripped error ceiling
        assert task.done()
        assert (
            self.mock_queue.send_content.call_count
            == self.watchdog.max_consecutive_errors
        )
        assert not self.watchdog.is_agent_turn
        assert self.watchdog.agent_turn_finished_event.is_set()
        assert not self.watchdog.is_closed
        self.mock_ws.close.assert_not_called()

    async def test_normal_dictation_flow_does_not_trigger_nudge(self):
        """During normal dictation (user speaks -> tool executes -> readback -> commit), no silence nudge is fired."""
        self.watchdog.silence_timeout_s = 0.1
        task = asyncio.create_task(
            self.watchdog.run(self.mock_queue, self.mock_ws)
        )

        # 1. User starts dictating notes (speech detected)
        self.watchdog.on_voice_detected()
        self.watchdog.on_user_speech()
        await asyncio.sleep(0.03)

        # 2. Model begins turn & runs stage_visit_notes tool
        self.watchdog.on_agent_turn_start()
        self.watchdog.on_tool_execution_start()
        await asyncio.sleep(0.04)

        # 3. Tool finishes executing
        self.watchdog.on_tool_execution_complete()
        await asyncio.sleep(0.02)

        # 4. Agent delivers readback speech
        self.watchdog.on_agent_turn_start()
        await asyncio.sleep(0.03)
        self.watchdog.on_agent_turn_complete()

        # 5. User confirms staged notes
        self.watchdog.on_user_speech()
        await asyncio.sleep(0.03)

        # 6. Commit succeeds
        self.watchdog.on_notes_committed()
        await asyncio.wait_for(task, timeout=0.5)

        # Watchdog terminates cleanly on commit without ever sending a prompt
        assert task.done()
        self.mock_queue.send_content.assert_not_called()
        assert self.watchdog.consecutive_silence_count == 0
        self.mock_ws.close.assert_not_called()
