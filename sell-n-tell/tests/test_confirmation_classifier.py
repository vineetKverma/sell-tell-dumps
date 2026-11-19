"""Unit tests for Confirmation Intent Classifier (AIML-3012)."""

from __future__ import annotations

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.voice_notes_agent.confirmation import (
    fast_prefilter,
    interpret,
    interpret_async,
)


class TestFastPrefilter:
    """Test 0ms fast-path prefilter for trivial transcripts."""

    @pytest.mark.parametrize(
        "empty_input",
        [
            "",
            "   ",
            "\t",
            "\n",
            "\r\n",
            None,
        ],
    )
    def test_empty_or_whitespace_is_unclear(self, empty_input):
        res = fast_prefilter(empty_input)
        assert res is not None
        assert res.intent == "unclear"

    @pytest.mark.parametrize(
        "punctuation_input",
        [
            ".",
            "...",
            "?",
            "!",
            ",",
            "-",
            "   ...   ",
            "???",
        ],
    )
    def test_punctuation_only_is_unclear(self, punctuation_input):
        res = fast_prefilter(punctuation_input)
        assert res is not None
        assert res.intent == "unclear"

    @pytest.mark.parametrize(
        "noise_token",
        [
            "[cough]",
            "[clears throat]",
            "[road noise]",
            "[traffic]",
            "[inaudible]",
            "[background noise]",
            "[static]",
            "*sigh*",
            "[noise]",
        ],
    )
    def test_acoustic_noise_tokens_are_unclear(self, noise_token):
        res = fast_prefilter(noise_token)
        assert res is not None
        assert res.intent == "unclear"

    def test_actual_speech_passes_through(self):
        assert fast_prefilter("Yeah") is None
        assert fast_prefilter("Yes, but change the date") is None
        assert fast_prefilter("Don't save") is None
        assert fast_prefilter("Uh, wait a minute") is None


class TestInterpretClassifier:
    """Test interpret() with mocked Google GenAI client."""

    def test_confirm_parsed_correctly(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "intent": "confirm",
                "correction_detail": None,
                "reasoning": "Clear affirmative response",
            }
        )
        mock_client.models.generate_content.return_value = mock_response

        res = interpret("Yeah, save it", client=mock_client)
        assert res.intent == "confirm"
        assert res.correction_detail is None

    def test_correction_parsed_correctly(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "intent": "correction",
                "correction_detail": "Change date to next Tuesday",
                "reasoning": "User agreed conditionally with a date change",
            }
        )
        mock_client.models.generate_content.return_value = mock_response

        res = interpret(
            "Yes, but change the date to next Tuesday", client=mock_client
        )
        assert res.intent == "correction"
        assert res.correction_detail == "Change date to next Tuesday"

    def test_skip_parsed_correctly(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "intent": "skip",
                "correction_detail": None,
                "reasoning": "User explicitly asked not to save",
            }
        )
        mock_client.models.generate_content.return_value = mock_response

        res = interpret("Don't save this note", client=mock_client)
        assert res.intent == "skip"

    def test_unclear_parsed_correctly(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "intent": "unclear",
                "correction_detail": None,
                "reasoning": "User asked clarification question",
            }
        )
        mock_client.models.generate_content.return_value = mock_response

        res = interpret("What did you say?", client=mock_client)
        assert res.intent == "unclear"

    def test_client_exception_fails_safe_to_unclear(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError(
            "API quota exceeded"
        )

        res = interpret("Yeah", client=mock_client)
        # Must fail safe to unclear so it never triggers false confirm!
        assert res.intent == "unclear"
        assert "RuntimeError" in (res.reasoning or "")

    def test_empty_model_response_fails_safe_to_unclear(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = ""
        mock_client.models.generate_content.return_value = mock_response

        res = interpret("Okay", client=mock_client)
        assert res.intent == "unclear"

    def test_interpret_async_parsed_correctly(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(
            {
                "intent": "confirm",
                "correction_detail": None,
                "reasoning": "Clear affirmative response",
            }
        )
        mock_client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )

        res = asyncio.run(
            interpret_async("Yeah, go ahead and save", client=mock_client)
        )
        assert res.intent == "confirm"
        assert res.correction_detail is None

    def test_interpret_async_exception_fails_safe_to_unclear(self):
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=RuntimeError("Connection dropped")
        )

        res = asyncio.run(interpret_async("Yeah", client=mock_client))
        assert res.intent == "unclear"
        assert "RuntimeError" in (res.reasoning or "")


class TestConfirmationSilenceWatchdog:
    """Test AIML-3012 Acceptance Criteria:

    'No reply within the timeout gives one reminder, then the notes stay
    unsaved and the rep is told so.'
    """

    def test_effective_max_prompts_is_two_when_notes_staged(self):
        from app.voice_notes_agent import notes_workflow
        from app.voice_notes_agent.silence_watchdog import SilenceWatchdog

        session_id = "test-session-watchdog-confirm"
        watchdog = SilenceWatchdog(session_id=session_id, max_silence_prompts=3)

        # Unstaged: default 3 prompts
        assert watchdog.get_effective_max_prompts() == 3

        # Staged: clamped to 2 prompts (1 reminder + 1 closing)
        notes_workflow._STAGED_NOTES[session_id] = {"record": {"visit_notes": {}}}
        try:
            assert watchdog.get_effective_max_prompts() == 2
        finally:
            notes_workflow._STAGED_NOTES.pop(session_id, None)

    def test_staged_final_prompt_explicitly_states_notes_stay_unsaved(self):
        from app.voice_notes_agent import notes_workflow
        from app.voice_notes_agent.silence_watchdog import SilenceWatchdog

        session_id = "test-session-watchdog-prompt"
        watchdog = SilenceWatchdog(session_id=session_id)
        notes_workflow._STAGED_NOTES[session_id] = {"record": {"visit_notes": {}}}
        try:
            # First silence (reminder)
            reminder = watchdog.build_nudge_prompt(count=1, is_final=False)
            assert "waiting for their confirmation" in reminder
            assert "Do NOT call commit_visit_notes" in reminder

            # Final silence (second timeout)
            final_prompt = watchdog.build_nudge_prompt(count=2, is_final=True)
            assert "closing this session" in final_prompt
            assert "notes stay unsaved" in final_prompt
            assert "left your notes unsaved" in final_prompt
            assert "Do NOT call commit_visit_notes" in final_prompt
        finally:
            notes_workflow._STAGED_NOTES.pop(session_id, None)


@pytest.fixture(autouse=True)
def reset_turn_guard_and_staged():
    """Autouse fixture to reset process-local turn guard state between tests."""
    from app.voice_notes_agent import turn_guard

    turn_guard._TURN_COUNTS.clear()
    turn_guard._LATEST_USER_TEXT.clear()
    turn_guard._BASELINES.clear()
    turn_guard._AWAITING_READBACK.clear()
    turn_guard._NUDGE_SENT.clear()
    turn_guard._AWAITING_TOOL.clear()
    yield
    turn_guard._TURN_COUNTS.clear()
    turn_guard._LATEST_USER_TEXT.clear()
    turn_guard._BASELINES.clear()
    turn_guard._AWAITING_READBACK.clear()
    turn_guard._NUDGE_SENT.clear()
    turn_guard._AWAITING_TOOL.clear()


def _run_tool_coro(coro):
    """Run an async ADK tool coroutine using asyncio."""
    return asyncio.run(coro)


class TestCommitVisitNotesIntentGate:
    """Test defense-in-depth gate in tools.commit_visit_notes (AIML-3012)."""

    def test_record_and_get_latest_user_text(self):
        from app.voice_notes_agent import turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, "yeah that sounds right")
        assert turn_guard.get_latest_user_text(session_id) == "yeah that sounds right"

    def test_record_user_turn_empty_clears_previous_text(self):
        from app.voice_notes_agent import turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, "yes save it")
        assert turn_guard.get_latest_user_text(session_id) == "yes save it"

        # An empty or whitespace-only turn should reset latest text
        turn_guard.record_user_turn(session_id, "   ")
        assert turn_guard.get_latest_user_text(session_id) == ""

    def test_cleanup_session_evicts_latest_user_text(self):
        from app.voice_notes_agent import turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, "some spoken text")
        assert session_id in turn_guard._LATEST_USER_TEXT

        turn_guard.cleanup_session(session_id)
        assert session_id not in turn_guard._LATEST_USER_TEXT

    @pytest.mark.parametrize(
        "empty_reply",
        [
            "",
            "   ",
            "\t",
            "\n",
            None,
        ],
    )
    def test_empty_or_whitespace_reply_blocks_commit_as_unclear(
        self, monkeypatch, empty_reply
    ):
        from unittest.mock import MagicMock

        from app.voice_notes_agent import tools, turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        if empty_reply is not None:
            turn_guard.record_user_turn(session_id, empty_reply)

        mock_context = MagicMock()
        mock_context.session.id = session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: session_id,
            "staged_record": {"session_id": session_id},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)
        monkeypatch.setattr(turn_guard, "has_new_reply", lambda ctx: True)

        res = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res["status"] == "error"
        assert res["error"] == "unclear_confirmation"
        assert "Do not call commit_visit_notes" in res["instruction_for_model"]

    @pytest.mark.parametrize(
        "noise_reply",
        [
            "[cough]",
            "...",
            "[clears throat]",
            "*sigh*",
        ],
    )
    def test_noise_reply_blocks_commit_as_unclear(self, monkeypatch, noise_reply):
        from unittest.mock import MagicMock

        from app.voice_notes_agent import tools, turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, noise_reply)

        mock_context = MagicMock()
        mock_context.session.id = session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: session_id,
            "staged_record": {"session_id": session_id},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)
        monkeypatch.setattr(turn_guard, "has_new_reply", lambda ctx: True)

        res = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res["status"] == "error"
        assert res["error"] == "unclear_confirmation"
        assert "Do not call commit_visit_notes" in res["instruction_for_model"]

    def test_correction_reply_blocks_commit_as_correction(self, monkeypatch):
        from unittest.mock import MagicMock

        from app.voice_notes_agent import confirmation, tools, turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, "yes but change date to tomorrow")

        mock_context = MagicMock()
        mock_context.session.id = session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: session_id,
            "staged_record": {"session_id": session_id},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)
        monkeypatch.setattr(turn_guard, "has_new_reply", lambda ctx: True)

        async def _mock_interpret_async(text, client=None):
            return confirmation.ConfirmationResult(
                intent="correction", correction_detail="change date to tomorrow"
            )

        monkeypatch.setattr(confirmation, "interpret_async", _mock_interpret_async)

        res = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res["status"] == "blocked"
        assert res["error"] == "correction_requested"
        assert "change date to tomorrow" in res["instruction_for_model"]

    def test_skip_reply_blocks_commit_as_skipped(self, monkeypatch):
        from unittest.mock import MagicMock

        from app.voice_notes_agent import confirmation, tools, turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, "no don't save that")

        mock_context = MagicMock()
        mock_context.session.id = session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: session_id,
            "staged_record": {"session_id": session_id},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)
        monkeypatch.setattr(turn_guard, "has_new_reply", lambda ctx: True)

        async def _mock_interpret_async(text, client=None):
            return confirmation.ConfirmationResult(intent="skip")

        monkeypatch.setattr(confirmation, "interpret_async", _mock_interpret_async)

        res = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res["status"] == "blocked"
        assert res["error"] == "save_skipped"
        assert "cancel or skip saving" in res["instruction_for_model"]

    def test_interpret_async_timeout_degrades_to_unclear(self, monkeypatch):
        from unittest.mock import MagicMock

        from app.voice_notes_agent import confirmation, tools, turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, "yes please")

        mock_context = MagicMock()
        mock_context.session.id = session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: session_id,
            "staged_record": {"session_id": session_id},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)
        monkeypatch.setattr(turn_guard, "has_new_reply", lambda ctx: True)
        monkeypatch.setattr(tools, "CONFIRMATION_TIMEOUT_S", 0.05)

        async def _slow_interpret_async(text, client=None):
            await asyncio.sleep(1.0)
            return confirmation.ConfirmationResult(intent="confirm")

        monkeypatch.setattr(confirmation, "interpret_async", _slow_interpret_async)

        res = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res["status"] == "error"
        assert res["error"] == "unclear_confirmation"

    def test_commit_visit_notes_retries_once_on_timeout_and_succeeds(self, monkeypatch):
        from unittest.mock import MagicMock

        from app.voice_notes_agent import (
            confirmation,
            notes_workflow,
            tools,
            turn_guard,
        )

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, "yes please save it")

        mock_context = MagicMock()
        mock_context.session.id = session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: session_id,
            "staged_record": {"session_id": session_id, "account_id": "ACC-123"},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)
        monkeypatch.setattr(turn_guard, "has_new_reply", lambda ctx: True)
        monkeypatch.setattr(tools, "CONFIRMATION_TIMEOUT_S", 0.05)

        call_count = 0

        async def _mock_interpret_async(text, client=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Attempt 1 times out
                await asyncio.sleep(1.0)
                return confirmation.ConfirmationResult(intent="confirm")
            # Attempt 2 succeeds quickly
            return confirmation.ConfirmationResult(intent="confirm")

        monkeypatch.setattr(confirmation, "interpret_async", _mock_interpret_async)
        monkeypatch.setattr(
            notes_workflow,
            "commit_notes",
            lambda sid, **kwargs: {
                "status": "committed",
                "session_id": sid,
                "payload": {"account_id": "ACC-123"},
            },
        )

        res = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res["status"] == "committed"
        assert res["session_id"] == session_id
        assert call_count == 2

    def test_commit_visit_notes_fatal_exception_does_not_retry(self, monkeypatch):
        from unittest.mock import MagicMock

        from app.voice_notes_agent import confirmation, tools, turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, "yes please")

        mock_context = MagicMock()
        mock_context.session.id = session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: session_id,
            "staged_record": {"session_id": session_id},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)
        monkeypatch.setattr(turn_guard, "has_new_reply", lambda ctx: True)

        call_count = 0

        async def _failing_interpret_async(text, client=None):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("Fatal client crash")

        monkeypatch.setattr(confirmation, "interpret_async", _failing_interpret_async)

        res = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res["status"] == "error"
        assert res["error"] == "unclear_confirmation"
        assert call_count == 1

    def test_happy_path_confirmation_proceeds_to_commit(self, monkeypatch):
        from unittest.mock import MagicMock

        from app.voice_notes_agent import (
            confirmation,
            notes_workflow,
            tools,
            turn_guard,
        )

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, "yes, go ahead and save it")

        mock_context = MagicMock()
        mock_context.session.id = session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: session_id,
            "staged_record": {"session_id": session_id, "account_id": "ACC-123"},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)
        monkeypatch.setattr(turn_guard, "has_new_reply", lambda ctx: True)

        async def _confirm_interpret_async(text, client=None):
            return confirmation.ConfirmationResult(intent="confirm")

        monkeypatch.setattr(confirmation, "interpret_async", _confirm_interpret_async)
        monkeypatch.setattr(
            notes_workflow,
            "commit_notes",
            lambda sid, **kwargs: {
                "status": "committed",
                "session_id": sid,
                "payload": {"account_id": "ACC-123"},
            },
        )

        res = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res["status"] == "committed"
        assert res["session_id"] == session_id

    def test_repeat_commit_attempt_blocked_after_gate_blocks(self, monkeypatch):
        from unittest.mock import MagicMock

        from app.voice_notes_agent import confirmation, tools, turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, "wait change contact to Jane")
        turn_guard.snapshot(MagicMock(session=MagicMock(id=session_id)))
        # User spoke another turn:
        turn_guard.record_user_turn(session_id, "change contact to Jane")

        mock_context = MagicMock()
        mock_context.session.id = session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: session_id,
            "staged_record": {"session_id": session_id},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)

        async def _mock_interpret_async(text, client=None):
            return confirmation.ConfirmationResult(
                intent="correction", correction_detail="change contact to Jane"
            )

        monkeypatch.setattr(confirmation, "interpret_async", _mock_interpret_async)

        # First call: blocked by intent gate
        res1 = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res1["status"] == "blocked"

        # Gate called turn_guard.snapshot(), so has_new_reply is now False!
        assert not turn_guard.has_new_reply(mock_context)

        # Immediate repeat call in same turn is now blocked by turn_guard
        res2 = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res2["status"] == "error"
        assert res2["error"] == "no_confirmation_heard"

    def test_commit_visit_notes_with_divergent_session_ids(self, monkeypatch):
        """Transcript lookup uses tool_context.session.id even when staged session ID differs."""
        from unittest.mock import MagicMock

        from app.voice_notes_agent import (
            confirmation,
            notes_workflow,
            tools,
            turn_guard,
        )

        ws_session_id = f"test-ws-{uuid.uuid4().hex[:8]}"
        staged_crm_id = f"test-crm-{uuid.uuid4().hex[:8]}"

        # User transcript is recorded under the WebSocket session ID (as in main.py)
        turn_guard.record_user_turn(ws_session_id, "yes, go ahead and save it")

        mock_context = MagicMock()
        mock_context.session.id = ws_session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: staged_crm_id,
            "staged_record": {"session_id": staged_crm_id, "account_id": "ACC-999"},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)
        monkeypatch.setattr(turn_guard, "has_new_reply", lambda ctx: True)

        async def _confirm_interpret_async(text, client=None):
            assert text == "yes, go ahead and save it"
            return confirmation.ConfirmationResult(intent="confirm")

        monkeypatch.setattr(confirmation, "interpret_async", _confirm_interpret_async)
        monkeypatch.setattr(
            notes_workflow,
            "commit_notes",
            lambda sid, confirmed=True, **kwargs: {
                "status": "committed",
                "session_id": sid,
            },
        )

        res = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res["status"] == "committed"
        assert res["session_id"] == staged_crm_id

    @pytest.mark.parametrize(
        "reply_text,expected_intent",
        [
            ("save what?", "unclear"),
            ("yes but change the date", "correction"),
            ("yeah no", "skip"),
        ],
    )
    def test_non_confirm_intent_blocks_commit(self, reply_text, expected_intent, monkeypatch):
        """Assert commit_visit_notes blocks and routes properly for non-confirm intents."""
        from unittest.mock import MagicMock

        from app.voice_notes_agent import confirmation, tools, turn_guard

        session_id = f"test-sid-{uuid.uuid4().hex[:8]}"
        turn_guard.record_user_turn(session_id, reply_text)

        mock_context = MagicMock()
        mock_context.session.id = session_id
        mock_context.state = {
            tools._STAGED_SESSION_KEY: session_id,
            "staged_record": {"session_id": session_id},
        }

        monkeypatch.setattr(turn_guard, "confirmation_was_read", lambda ctx: True)
        monkeypatch.setattr(turn_guard, "has_new_reply", lambda ctx: True)

        async def _mock_interpret_async(text, client=None):
            return confirmation.ConfirmationResult(intent=expected_intent)

        monkeypatch.setattr(confirmation, "interpret_async", _mock_interpret_async)

        res = _run_tool_coro(tools.commit_visit_notes(mock_context))
        assert res["status"] in ("blocked", "error")
        assert res.get("error") != "no_confirmation_heard"


class TestConfirmationClientAndConfig:
    """Test dedicated confirmation client resolution, thinking config, and self-checks."""

    def test_generation_config_has_zero_thinking_budget_and_256_tokens(self):
        from app.voice_notes_agent.confirmation import _build_generation_config

        config = _build_generation_config()
        assert config.max_output_tokens == 256
        assert config.thinking_config is not None
        assert config.thinking_config.thinking_budget == 0

    def test_prewarm_confirmation_client_explicit(self):
        from app.voice_notes_agent import confirmation

        mock_client = MagicMock()
        registered = confirmation.prewarm_confirmation_client(mock_client)
        assert registered is mock_client
        assert confirmation._CLIENT_CACHE["client"] is mock_client
        confirmation._CLIENT_CACHE["client"] = None

    def test_prewarm_confirmation_client_pins_location_to_global(self, monkeypatch):
        import sys

        from app.voice_notes_agent import confirmation

        confirmation._CLIENT_CACHE["client"] = None
        mock_live = MagicMock()
        mock_live._api_client.location = "us-central1"
        mock_live._api_client.project = "test-proj"
        mock_creds = MagicMock()
        mock_live._api_client._credentials = mock_creds

        mock_agent_mod = MagicMock()
        mock_agent_mod.live_client = mock_live
        pkg_prefix = confirmation.__name__.rsplit(".", 1)[0]
        monkeypatch.setitem(sys.modules, f"{pkg_prefix}.agent", mock_agent_mod)

        captured_kwargs = {}

        def mock_client_init(*args, **kwargs):
            captured_kwargs.update(kwargs)
            m = MagicMock()
            m._api_client.location = kwargs.get("location")
            return m

        monkeypatch.setattr("google.genai.Client", mock_client_init)
        monkeypatch.setenv("CONFIRMATION_LOCATION", "global")

        client = confirmation.prewarm_confirmation_client()
        assert client is not None
        assert captured_kwargs.get("location") == "global"
        assert captured_kwargs.get("credentials") is mock_creds
        confirmation._CLIENT_CACHE["client"] = None

    def test_check_confirmation_client(self):
        from app.voice_notes_agent.confirmation import check_confirmation_client

        mock_c = MagicMock()
        mock_c._api_client.location = "global"
        mock_c._api_client.project = "test-proj"
        mock_c._api_client._credentials = MagicMock()
        mock_c._api_client._credentials.valid = True

        status = check_confirmation_client(mock_c)
        assert status["configured"] is True
        assert status["location"] == "global"
        assert status["has_credentials"] is True
        assert status["credentials_valid"] is True

    @pytest.mark.asyncio
    async def test_probe_confirmation_client_success(self):
        from app.voice_notes_agent.confirmation import probe_confirmation_client

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "intent": "confirm",
            "correction_detail": None,
            "reasoning": "Clear affirmative response",
        })
        mock_response.candidates = []
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        success = await probe_confirmation_client(client=mock_client)
        assert success is True

    @pytest.mark.asyncio
    async def test_probe_confirmation_client_non_confirm_fails(self, caplog):
        import logging

        from app.voice_notes_agent.confirmation import probe_confirmation_client

        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps({
            "intent": "unclear",
            "correction_detail": None,
            "reasoning": "Classification failed with exception: 404 NOT_FOUND",
        })
        mock_response.candidates = []
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with caplog.at_level(logging.ERROR):
            success = await probe_confirmation_client(client=mock_client)
            assert success is False
            error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert len(error_records) == 1
            assert "probe failed" in error_records[0].message.lower()

    @pytest.mark.asyncio
    async def test_probe_confirmation_client_timeout_fails(self, caplog):
        import logging

        from app.voice_notes_agent.confirmation import probe_confirmation_client

        mock_client = MagicMock()

        async def slow_generate(*args, **kwargs):
            await asyncio.sleep(0.5)

        mock_client.aio.models.generate_content = AsyncMock(side_effect=slow_generate)

        with caplog.at_level(logging.ERROR):
            success = await probe_confirmation_client(client=mock_client, timeout=0.01)
            assert success is False
            error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
            assert len(error_records) == 1
            assert "timed out" in error_records[0].message.lower()


