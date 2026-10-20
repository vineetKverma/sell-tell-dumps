"""Tests for AudioEnergyDetector and VAD grace window in SilenceWatchdog."""

from __future__ import annotations

import asyncio
import struct
from unittest.mock import patch

import pytest

from app.voice_notes_agent.audio_detector import AudioEnergyDetector
from app.voice_notes_agent.silence_watchdog import SilenceWatchdog

_EXPECTED_MAX_NOISE_FLOOR = 300.0


def make_pcm_chunk(amplitude: int, n_samples: int = 320) -> bytes:
    """Generate a synthetic 16-bit PCM chunk with given sample amplitude."""
    return struct.pack(f"<{n_samples}h", *([amplitude] * n_samples))


def test_audio_detector_silence_and_ambient():
    """Ambient noise below threshold should never trigger voice activity."""
    detector = AudioEnergyDetector(min_speech_rms=400.0, min_speech_frames=5)
    ambient_chunk = make_pcm_chunk(amplitude=120)

    for _ in range(20):
        is_speech = detector.update(ambient_chunk)
        assert not is_speech
    assert detector.noise_floor < _EXPECTED_MAX_NOISE_FLOOR


def test_audio_detector_rejects_brief_noise_spikes():
    """Brief impulses (1-2 frames of high amplitude) should NOT declare speech."""
    detector = AudioEnergyDetector(min_speech_rms=400.0, min_speech_frames=5)
    ambient_chunk = make_pcm_chunk(amplitude=80)
    loud_spike = make_pcm_chunk(amplitude=3000)

    # Ambient baseline
    for _ in range(10):
        detector.update(ambient_chunk)

    # 2-frame spike (e.g. 40ms cough / click)
    assert not detector.update(loud_spike)
    assert not detector.update(loud_spike)

    # Returns to ambient
    for _ in range(10):
        assert not detector.update(ambient_chunk)
    assert not detector.is_speech_active


def test_audio_detector_sustained_speech():
    """Sustained voice energy (>5 consecutive frames) declares speech and decays."""
    detector = AudioEnergyDetector(min_speech_rms=400.0, min_speech_frames=5)
    speech_chunk = make_pcm_chunk(amplitude=2500)
    silence_chunk = make_pcm_chunk(amplitude=50)

    # Frames 1-4: accumulating
    for _ in range(4):
        assert not detector.update(speech_chunk)

    # Frame 5: threshold met!
    assert detector.update(speech_chunk)
    # Further speech frames remain active
    assert detector.update(speech_chunk)

    # Now silence arrives: should decay back to inactive
    decayed = False
    for _ in range(10):
        if not detector.update(silence_chunk):
            decayed = True
            break
    assert decayed


def test_audio_detector_counter_clamped_and_fast_decay():
    """Verify speech counter is capped and silence immediately drops active state."""
    min_speech_frames = 5
    detector = AudioEnergyDetector(
        min_speech_rms=400.0, min_speech_frames=min_speech_frames
    )
    speech_chunk = make_pcm_chunk(amplitude=2500)
    silence_chunk = make_pcm_chunk(amplitude=50)

    # Simulate 10 seconds of talking (500 frames)
    for _ in range(500):
        detector.update(speech_chunk)

    assert detector.is_speech_active
    # Counter must be clamped to min_speech_frames * 2 (10)
    assert detector.consecutive_speech_frames <= min_speech_frames * 2

    # Verify silence resets is_speech_active within at most 5 frames (100ms)
    _MAX_DECAY_FRAMES = 5
    quiet_frames_to_decay = 0
    while detector.is_speech_active:
        detector.update(silence_chunk)
        quiet_frames_to_decay += 1
        assert quiet_frames_to_decay <= _MAX_DECAY_FRAMES, (
            "Speech counter failed to decay rapidly"
        )

    assert not detector.is_speech_active


def test_silence_watchdog_cumulative_grace_cap():
    """Verify persistent noise cannot extend grace window past cumulative budget."""
    total_budget = 10.0
    first_grant = 7.0
    expected_remaining = total_budget - first_grant
    watchdog = SilenceWatchdog(
        session_id="test-session-budget",
        silence_timeout_s=5.0,
        max_unverified_grace_s=total_budget,
    )

    base_time = 100.0
    expected_grace_1 = base_time + first_grant
    expected_grace_2 = base_time + total_budget

    with patch("time.monotonic") as mock_time:
        mock_time.return_value = base_time
        # t=100: first detection grants 7.0s grace (budget 10 -> 3)
        watchdog.on_voice_detected(grace_seconds=first_grant)
        assert (
            watchdog._cumulative_grace_budget_remaining_s == expected_remaining
        )
        assert watchdog._voice_grace_until == expected_grace_1

        # t=104: 4s later, noise continues and requests another 7.0s (target 111.0)
        # Needed beyond 107.0 is 4.0s. Budget remaining is 3.0s, so grant is 3.0s.
        mock_time.return_value = base_time + 4.0
        watchdog.on_voice_detected(grace_seconds=first_grant)
        assert watchdog._cumulative_grace_budget_remaining_s == 0.0
        assert watchdog._voice_grace_until == expected_grace_2

        # t=108: more persistent noise, but budget is exhausted -> no extension
        mock_time.return_value = base_time + 8.0
        watchdog.on_voice_detected(grace_seconds=first_grant)
        assert watchdog._cumulative_grace_budget_remaining_s == 0.0
        assert watchdog._voice_grace_until == expected_grace_2

        # STT confirmed words resets the cumulative budget
        watchdog.on_user_speech()
        assert watchdog._cumulative_grace_budget_remaining_s == total_budget


@pytest.mark.asyncio
async def test_silence_watchdog_voice_grace_prevents_premature_nudge():
    """When voice activity is detected near timeout, grace window holds off nudge."""
    watchdog = SilenceWatchdog(
        session_id="test-session-grace",
        silence_timeout_s=0.3,
        max_silence_prompts=3,
        settle_delay_s=0.01,
    )

    class DummyQueue:
        def __init__(self):
            self.prompts = []

        def send_content(self, content):
            self.prompts.append(content)

    dummy_queue = DummyQueue()
    ready = asyncio.Event()
    ready.set()

    task = asyncio.create_task(
        watchdog.run(dummy_queue, None, ready_event=ready)  # type: ignore[arg-type]
    )

    # Sleep 0.2s (out of 0.3s timeout)
    await asyncio.sleep(0.2)
    assert watchdog.consecutive_silence_count == 0

    # User starts speaking! Grant 0.3s grace
    watchdog.on_voice_detected(grace_seconds=0.3)

    # Sleep past original 0.3s timeout (total 0.35s since start)
    await asyncio.sleep(0.15)
    # Nudge should NOT have fired because grace window is active
    assert watchdog.consecutive_silence_count == 0
    assert len(dummy_queue.prompts) == 0

    # STT confirms user speech
    watchdog.on_user_speech()
    assert watchdog.consecutive_silence_count == 0
    assert watchdog._voice_grace_until == 0.0

    watchdog.is_closed = True
    watchdog.wake_event.set()
    await asyncio.sleep(0.05)
    task.cancel()
