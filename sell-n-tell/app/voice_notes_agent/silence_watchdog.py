"""Silence and Inactivity Watchdog for the Voice Notes Agent.

Monitors user inactivity across all turns (Turn 0 through commit). When the user
remains silent for ``VOICE_NOTES_SILENCE_TIMEOUT_SECONDS``, it provokes Gemini
Live to speak a natural-language prompt out loud. If the user remains silent
after ``VOICE_NOTES_MAX_SILENCE_PROMPTS`` consecutive attempts, it instructs
the agent to say goodbye and cleanly closes the WebSocket session.

If the user speaks at any point (including barging in while the agent is
speaking a provocation), the silence counter is reset to 0 and normal processing
resumes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

from google.genai import types
from starlette.websockets import WebSocketDisconnect

from . import notes_workflow, turn_guard
from .config import (
    VOICE_NOTES_MAX_SILENCE_PROMPTS,
    VOICE_NOTES_SILENCE_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:
    from fastapi import WebSocket
    from google.adk.agents.live_request_queue import LiveRequestQueue

logger = logging.getLogger(__name__)

_DEFAULT_SETTLE_DELAY_S = 0.4
_DEFAULT_GOODBYE_GRACE_S = 3.0
_DEFAULT_AGENT_TURN_TIMEOUT_S = 15.0
_DEFAULT_MAX_UNVERIFIED_GRACE_S = 15.0
_DEFAULT_TOOL_EXECUTION_TIMEOUT_S = 60.0
_DEFAULT_MAX_CONSECUTIVE_ERRORS = 3
_TIMEOUT_FUZZ_S = 0.05
_READBACK_CHECK_INTERVAL_S = 0.5
_DEFAULT_AUDIO_SAMPLE_RATE_HZ = 24000
_DEFAULT_AUDIO_BYTES_PER_SAMPLE = 2  # 16-bit linear PCM mono
_DEFAULT_AUDIO_BYTES_PER_SECOND = (
    _DEFAULT_AUDIO_SAMPLE_RATE_HZ * _DEFAULT_AUDIO_BYTES_PER_SAMPLE
)


class SilenceWatchdog:
    """Manages inactivity detection, prompts, and session termination."""

    def __init__(
        self,
        session_id: str,
        *,
        silence_timeout_s: float | None = None,
        max_silence_prompts: int | None = None,
        settle_delay_s: float = _DEFAULT_SETTLE_DELAY_S,
        goodbye_grace_s: float = _DEFAULT_GOODBYE_GRACE_S,
        agent_turn_timeout_s: float = _DEFAULT_AGENT_TURN_TIMEOUT_S,
        max_unverified_grace_s: float = _DEFAULT_MAX_UNVERIFIED_GRACE_S,
        tool_execution_timeout_s: float = _DEFAULT_TOOL_EXECUTION_TIMEOUT_S,
        max_consecutive_errors: int = _DEFAULT_MAX_CONSECUTIVE_ERRORS,
    ) -> None:
        self.session_id = session_id
        self.silence_timeout_s = (
            silence_timeout_s
            if silence_timeout_s is not None
            else float(VOICE_NOTES_SILENCE_TIMEOUT_SECONDS)
        )
        self.max_silence_prompts = (
            max_silence_prompts
            if max_silence_prompts is not None
            else int(VOICE_NOTES_MAX_SILENCE_PROMPTS)
        )
        self.settle_delay_s = settle_delay_s
        self.goodbye_grace_s = goodbye_grace_s
        self.agent_turn_timeout_s = agent_turn_timeout_s
        self.max_unverified_grace_s = max_unverified_grace_s
        self.tool_execution_timeout_s = tool_execution_timeout_s
        self.max_consecutive_errors = max_consecutive_errors

        self.consecutive_silence_count = 0
        self.is_agent_turn = False
        self.is_tool_executing = False
        self._tool_start_time = 0.0
        self.is_committed = False
        self.is_closed = False
        self._last_activity_time = time.monotonic()
        self._voice_grace_until = 0.0
        self._cumulative_grace_budget_remaining_s = max_unverified_grace_s
        self._playback_end = 0.0

        self.wake_event = asyncio.Event()
        self.user_spoke_event = asyncio.Event()
        self.agent_turn_finished_event = asyncio.Event()
        self.agent_turn_finished_event.set()

    def on_voice_detected(self, grace_seconds: float = 7.0) -> None:
        """Called in real time by VAD when candidate speech energy is detected.

        Extends the silence timer by a grace period so the user is never
        interrupted while actively dictating.
        """
        if self.is_agent_turn or self.is_committed or self.is_closed:
            return

        if self._cumulative_grace_budget_remaining_s <= 0.0:
            return

        now = time.monotonic()
        target_grace_until = now + grace_seconds
        current_deadline = max(now, self._voice_grace_until)
        needed = max(0.0, target_grace_until - current_deadline)
        grant = min(needed, self._cumulative_grace_budget_remaining_s)

        if grant > 0.0:
            self._cumulative_grace_budget_remaining_s -= grant
            self._voice_grace_until = current_deadline + grant
            self.wake_event.set()

    def on_user_speech(self) -> None:
        """Called when valid user speech or text input is detected."""
        if self.consecutive_silence_count > 0:
            logger.info(
                "SilenceWatchdog(session_id=%s): User speech detected. "
                "Resetting silence count from %d to 0.",
                self.session_id,
                self.consecutive_silence_count,
            )
        self.consecutive_silence_count = 0
        self._voice_grace_until = 0.0
        self._cumulative_grace_budget_remaining_s = self.max_unverified_grace_s
        self._last_activity_time = time.monotonic()
        self._playback_end = 0.0
        self.is_agent_turn = False
        self.is_tool_executing = False
        self._tool_start_time = 0.0
        self.agent_turn_finished_event.set()
        self.user_spoke_event.set()
        self.wake_event.set()

    def on_agent_turn_start(self) -> None:
        """Called when the agent starts speaking or running a tool."""
        self.is_agent_turn = True
        self._voice_grace_until = 0.0
        self._cumulative_grace_budget_remaining_s = self.max_unverified_grace_s
        self.agent_turn_finished_event.clear()
        self.wake_event.set()

    def on_agent_audio(self, byte_count: int) -> None:
        """Accumulate streamed audio bytes into a running playback cursor."""
        if self.is_agent_turn and byte_count > 0:
            self._playback_end = (
                max(self._playback_end, time.monotonic())
                + byte_count / _DEFAULT_AUDIO_BYTES_PER_SECOND
            )

    def on_tool_execution_start(self) -> None:
        """Called when a tool call begins executing."""
        self.is_tool_executing = True
        self._tool_start_time = time.monotonic()
        self.is_agent_turn = True
        self._voice_grace_until = 0.0
        self._cumulative_grace_budget_remaining_s = self.max_unverified_grace_s
        self.wake_event.set()

    def on_tool_execution_complete(self) -> None:
        """Called when a tool call finishes executing."""
        self.is_tool_executing = False
        self._tool_start_time = 0.0
        self._last_activity_time = time.monotonic()
        self.wake_event.set()

    def on_agent_turn_complete(self) -> None:
        """Called when Gemini emits turn_complete."""
        now = time.monotonic()
        self._last_activity_time = max(now, self._playback_end)

        self.is_agent_turn = False
        self.is_tool_executing = False
        self._tool_start_time = 0.0
        self._voice_grace_until = 0.0
        self._cumulative_grace_budget_remaining_s = self.max_unverified_grace_s
        self.agent_turn_finished_event.set()
        self.wake_event.set()

    def on_notes_committed(self) -> None:
        """Called when visit notes are committed; halts watchdog."""
        self.is_committed = True
        self.is_agent_turn = False
        self.is_tool_executing = False
        self._tool_start_time = 0.0
        self._playback_end = 0.0
        self.agent_turn_finished_event.set()
        self.user_spoke_event.set()
        self.wake_event.set()

    def build_nudge_prompt(self, count: int, is_final: bool) -> str:
        """Construct context-aware prompt text for Gemini Live."""
        staged = notes_workflow.get_staged(self.session_id)
        if staged is None:
            return self._build_unstaged_prompt(count, is_final)
        return self._build_staged_prompt(count, is_final)

    def _build_unstaged_prompt(self, count: int, is_final: bool) -> str:
        if is_final:
            return (
                "(automated check-in) The user has remained silent after "
                "multiple prompts and has not started dictating notes. Politely "
                "inform the user out loud that you are closing this session "
                "due to inactivity, say goodbye, and do not say anything "
                "further. Do NOT call any tools."
            )
        if count == 1:
            return (
                "(automated check-in) The user has been silent and has not "
                "spoken yet. Politely ask the user out loud if they are ready "
                "to begin dictating their visit notes. Keep it concise "
                "(1-2 sentences). Do NOT call any tools."
            )
        return (
            "(automated check-in) The user is still silent. Prompt the user "
            "again out loud, asking if they can hear you and if they are ready "
            "to begin their visit notes. Keep it concise (1-2 sentences). "
            "Do NOT call any tools."
        )

    def _build_staged_prompt(self, count: int, is_final: bool) -> str:
        if is_final:
            return (
                "(automated check-in) The user has remained silent after "
                "multiple prompts and has not confirmed the staged notes. "
                "Politely inform the user out loud that you are closing this "
                "session due to inactivity, say goodbye, and do not say anything "
                "further. Do NOT call any tools."
            )
        if count == 1:
            return (
                "(automated check-in) The user has been silent for a while. "
                "Politely remind the user out loud that you are waiting for their "
                "confirmation to save the staged notes or make any changes. "
                "Keep it concise (1-2 sentences). "
                "Do NOT call commit_visit_notes or any other tools."
            )
        return (
            "(automated check-in) The user is still silent. Prompt the user "
            "again out loud, asking if they would like you to save the staged "
            "notes or if they need any adjustments. Keep it concise "
            "(1-2 sentences). Do NOT call commit_visit_notes or any other tools."
        )

    async def _wait_for_agent_turn(self) -> None:
        """Wait for agent to finish speaking with a safe fallback timeout."""
        while (
            self.is_agent_turn and not self.is_closed and not self.is_committed
        ):
            if self.is_tool_executing:
                if (
                    time.monotonic() - self._tool_start_time
                    > self.tool_execution_timeout_s
                ):
                    logger.warning(
                        "SilenceWatchdog(session_id=%s): Tool execution "
                        "exceeded ceiling of %.1fs; releasing tool hold.",
                        self.session_id,
                        self.tool_execution_timeout_s,
                    )
                    self.is_tool_executing = False
                    self._tool_start_time = 0.0
                    self.is_agent_turn = False
                    self.agent_turn_finished_event.set()
                    break
                self._last_activity_time = time.monotonic()
                poll_interval = min(
                    _READBACK_CHECK_INTERVAL_S,
                    max(0.01, self.tool_execution_timeout_s / 2),
                )
                await asyncio.sleep(poll_interval)
                continue
            try:
                await asyncio.wait_for(
                    self.agent_turn_finished_event.wait(),
                    timeout=self.agent_turn_timeout_s,
                )
                break
            except asyncio.TimeoutError:
                if self.is_tool_executing:
                    self._last_activity_time = time.monotonic()
                    continue
                logger.warning(
                    "SilenceWatchdog(session_id=%s): Timed out waiting for "
                    "agent turn completion after %.1fs; resuming monitoring.",
                    self.session_id,
                    self.agent_turn_timeout_s,
                )
                self.is_agent_turn = False
                self.agent_turn_finished_event.set()
                break

    async def _handle_prompt_cycle(
        self,
        live_request_queue: LiveRequestQueue,
        websocket: WebSocket,
    ) -> bool:
        """Send prompt to Gemini Live and wait for delivery."""
        count = self.consecutive_silence_count + 1
        is_final = count >= self.max_silence_prompts

        self.user_spoke_event.clear()
        await asyncio.sleep(self.settle_delay_s)
        if (
            self.user_spoke_event.is_set()
            or time.monotonic() < self._voice_grace_until
            or self.is_committed
            or self.is_closed
            or self.is_agent_turn
            or self.is_tool_executing
        ):
            return False

        prompt_text = self.build_nudge_prompt(count, is_final=is_final)
        self.consecutive_silence_count += 1
        count = self.consecutive_silence_count
        logger.warning(
            "SilenceWatchdog(session_id=%s): Inactivity detected "
            "(prompt #%d/%d).",
            self.session_id,
            count,
            self.max_silence_prompts,
        )

        if is_final:
            logger.info(
                "SilenceWatchdog(session_id=%s): Final silence prompt reached. "
                "Injecting closing statement.",
                self.session_id,
            )
        self.is_agent_turn = True
        self.agent_turn_finished_event.clear()
        try:
            live_request_queue.send_content(
                types.Content(parts=[types.Part(text=prompt_text)])
            )
        except Exception:
            self.is_agent_turn = False
            self.agent_turn_finished_event.set()
            raise

        await self._wait_for_agent_turn()
        self._last_activity_time = max(
            self._last_activity_time, time.monotonic()
        )

        if is_final:
            await asyncio.sleep(self.goodbye_grace_s)
            if (
                self.consecutive_silence_count >= self.max_silence_prompts
                and not self.is_committed
                and not self.is_closed
            ):
                logger.info(
                    "SilenceWatchdog(session_id=%s): Closing session due to "
                    "inactivity.",
                    self.session_id,
                )
                self.is_closed = True
                try:
                    await websocket.close(
                        code=1000, reason="inactivity_timeout"
                    )
                except (WebSocketDisconnect, RuntimeError):
                    pass
                return True
        return False

    async def _wait_for_next_cycle(self) -> bool:
        """Wait for turn completion, readback, grace window, or timeout.

        Returns True if inactivity timeout has expired and nudge should fire.
        """
        if self.is_tool_executing and (
            time.monotonic() - self._tool_start_time
            > self.tool_execution_timeout_s
        ):
            logger.warning(
                "SilenceWatchdog(session_id=%s): Tool execution exceeded "
                "ceiling of %.1fs; releasing tool hold.",
                self.session_id,
                self.tool_execution_timeout_s,
            )
            self.is_tool_executing = False
            self._tool_start_time = 0.0
            self.is_agent_turn = False
            self.agent_turn_finished_event.set()

        if self.is_agent_turn or self.is_tool_executing:
            await self._wait_for_agent_turn()
            self._last_activity_time = max(
                self._last_activity_time, time.monotonic()
            )
            return False

        if turn_guard.needs_readback_nudge(self.session_id):
            self._last_activity_time = time.monotonic()
            await asyncio.sleep(_READBACK_CHECK_INTERVAL_S)
            return False

        now = time.monotonic()
        if now < self._voice_grace_until:
            grace_remaining = self._voice_grace_until - now
            self.wake_event.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self.wake_event.wait(), timeout=grace_remaining
                )
            return False

        elapsed = time.monotonic() - self._last_activity_time
        remaining = self.silence_timeout_s - elapsed
        if remaining > 0:
            self.wake_event.clear()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(
                    self.wake_event.wait(), timeout=remaining
                )
            return False

        if (
            self.is_committed
            or self.is_closed
            or self.is_agent_turn
            or self.is_tool_executing
            or time.monotonic() < self._voice_grace_until
            or (time.monotonic() - self._last_activity_time)
            < (self.silence_timeout_s - _TIMEOUT_FUZZ_S)
        ):
            return False

        return True

    async def run(
        self,
        live_request_queue: LiveRequestQueue,
        websocket: WebSocket,
        ready_event: asyncio.Event | None = None,
    ) -> None:
        """Main async monitoring loop."""
        try:
            if ready_event is not None:
                await ready_event.wait()

            self._last_activity_time = time.monotonic()
            logger.info(
                "SilenceWatchdog started: session_id=%s, timeout=%.1fs, "
                "max_prompts=%d",
                self.session_id,
                self.silence_timeout_s,
                self.max_silence_prompts,
            )

            consecutive_errors = 0
            max_consecutive_errors = self.max_consecutive_errors
            while not self.is_committed and not self.is_closed:
                try:
                    should_prompt = await self._wait_for_next_cycle()
                    if should_prompt and not (
                        self.is_committed
                        or self.is_closed
                        or self.is_agent_turn
                        or self.is_tool_executing
                    ):
                        if await self._handle_prompt_cycle(
                            live_request_queue, websocket
                        ):
                            break
                    consecutive_errors = 0
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    consecutive_errors += 1
                    logger.error(
                        "SilenceWatchdog error for session %s (error %d/%d): %s",
                        self.session_id,
                        consecutive_errors,
                        max_consecutive_errors,
                        exc,
                        exc_info=True,
                    )
                    if consecutive_errors >= max_consecutive_errors:
                        logger.warning(
                            "SilenceWatchdog for session %s reached error threshold; "
                            "disabling watchdog to preserve session.",
                            self.session_id,
                        )
                        break
                    self._last_activity_time = time.monotonic()
                    await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "SilenceWatchdog startup error for session %s: %s",
                self.session_id,
                exc,
                exc_info=True,
            )
