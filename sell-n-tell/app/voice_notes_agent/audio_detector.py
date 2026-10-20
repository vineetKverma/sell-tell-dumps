"""Audio energy detector and lightweight Voice Activity Detector (VAD).

Analyzes raw 16kHz 16-bit linear PCM audio chunks from browser microphones
to detect sustained speech vs. ambient noise and brief impulse spikes (clicks,
keyboard taps, coughs).
"""

from __future__ import annotations

import array
import math

_MIN_BYTES = 2
_MAX_CLAMPED_RMS = 1500.0
_MIN_NOISE_FLOOR = 40.0


class AudioEnergyDetector:
    """Lightweight adaptive voice activity detector for 16-bit 16kHz mono PCM."""

    def __init__(
        self,
        min_speech_rms: float = 350.0,
        snr_multiplier: float = 2.5,
        min_speech_frames: int = 5,
        floor_alpha: float = 0.05,
    ) -> None:
        """Initialize detector.

        Args:
            min_speech_rms: Absolute minimum RMS amplitude to consider as voice.
            snr_multiplier: Multiplier over adaptive ambient noise floor.
            min_speech_frames: Number of consecutive frames above threshold
                required to declare voice activity (~100-200ms of audio).
            floor_alpha: Exponential moving average factor for noise floor.
        """
        self.min_speech_rms = min_speech_rms
        self.snr_multiplier = snr_multiplier
        self.min_speech_frames = min_speech_frames
        self.floor_alpha = floor_alpha

        self.noise_floor: float = 100.0
        self.consecutive_speech_frames: int = 0
        self.is_speech_active: bool = False

    def compute_rms(self, audio_bytes: bytes) -> float:
        """Compute Root Mean Square amplitude of 16-bit PCM buffer."""
        if not audio_bytes or len(audio_bytes) < _MIN_BYTES:
            return 0.0
        n_bytes = len(audio_bytes) - (len(audio_bytes) % 2)
        if n_bytes < _MIN_BYTES:
            return 0.0

        samples = array.array("h")
        samples.frombytes(audio_bytes[:n_bytes])
        n_samples = len(samples)
        if n_samples == 0:
            return 0.0

        sum_sq = sum(s * s for s in samples)
        return math.sqrt(sum_sq / n_samples)

    def update(self, audio_bytes: bytes) -> bool:
        """Process incoming audio chunk and return True if speech is active."""
        rms = self.compute_rms(audio_bytes)
        threshold = max(
            self.min_speech_rms, self.noise_floor * self.snr_multiplier
        )

        if rms >= threshold:
            # Saturating counter: cap accumulation to avoid delayed decay
            max_frames = self.min_speech_frames * 2
            self.consecutive_speech_frames = min(
                self.consecutive_speech_frames + 1, max_frames
            )
            if self.consecutive_speech_frames >= self.min_speech_frames:
                self.is_speech_active = True
                return True
        else:
            # Gradually decay speech frame counter
            self.consecutive_speech_frames = max(
                0, self.consecutive_speech_frames - 2
            )
            if self.consecutive_speech_frames == 0:
                self.is_speech_active = False
            # Update ambient noise floor only during silence
            if not self.is_speech_active:
                clamped_rms = min(rms, _MAX_CLAMPED_RMS)
                self.noise_floor = (
                    1.0 - self.floor_alpha
                ) * self.noise_floor + self.floor_alpha * clamped_rms
                self.noise_floor = max(_MIN_NOISE_FLOOR, self.noise_floor)

        return self.is_speech_active
