"""Audio stimulation module.

Plays an audio file (e.g. a pink noise pulse) when stimulation events
are detected. Designed for auditory closed-loop stimulation during sleep.

The audio is played in a background thread to avoid blocking the
processing pipeline. Uses the platform's default audio output.

Requires: simpleaudio (pip install simpleaudio) or falls back to a
subprocess call to the system audio player.
"""

from __future__ import annotations

import logging
import threading
import wave
from pathlib import Path

import numpy as np

from dnb.core.types import Event, EventType, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class AudioStimulator(Module):
    """Play an audio stimulus on STIM1 and/or STIM2 events.

    The module checks each event in the ProcessResult. When it finds
    a matching event type, it plays the configured WAV file on the
    default audio output.

    Args:
        wav_path: Path to the WAV file to play.
        trigger_on: Which event types trigger playback.
        volume: Volume scaling factor (0.0 to 1.0).
    """

    def __init__(
        self,
        wav_path: str | Path,
        trigger_on: tuple[EventType, ...] = (EventType.STIM1, EventType.STIM2),
        volume: float = 1.0,
    ) -> None:
        self._wav_path = Path(wav_path)
        self._trigger_on = trigger_on
        self._volume = max(0.0, min(1.0, volume))

        # Audio data loaded during configure()
        self._audio_data: np.ndarray | None = None
        self._sample_rate: int = 0
        self._n_channels: int = 0
        self._sample_width: int = 0
        self._sa_available = False
        self._stim_count = 0

    def configure(self, config: PipelineConfig) -> None:
        if not self._wav_path.exists():
            logger.error("Audio file not found: %s", self._wav_path)
            return

        # Load WAV file
        try:
            with wave.open(str(self._wav_path), "rb") as wf:
                self._sample_rate = wf.getframerate()
                self._n_channels = wf.getnchannels()
                self._sample_width = wf.getsampwidth()
                n_frames = wf.getnframes()
                raw = wf.readframes(n_frames)
                self._audio_data = np.frombuffer(raw, dtype=np.int16).copy()

                # Apply volume
                if self._volume < 1.0:
                    scaled = (self._audio_data.astype(np.float64) * self._volume)
                    self._audio_data = scaled.clip(-32768, 32767).astype(np.int16)

            logger.info(
                "AudioStimulator loaded: %s (%.2fs, %d Hz, %d ch)",
                self._wav_path.name,
                n_frames / self._sample_rate,
                self._sample_rate,
                self._n_channels,
            )
        except Exception:
            logger.exception("Failed to load audio file: %s", self._wav_path)
            self._audio_data = None
            return

        # Check for simpleaudio
        try:
            import simpleaudio
            self._sa_available = True
            logger.info("Using simpleaudio for playback")
        except ImportError:
            self._sa_available = False
            logger.warning(
                "simpleaudio not available — audio stimulation will be logged "
                "but not played. Install with: pip install simpleaudio"
            )

    def process(self, result: ProcessResult) -> ProcessResult:
        for event in result.events:
            if event.event_type in self._trigger_on:
                self._stim_count += 1
                self._play(event)
        return result

    def _play(self, event: Event) -> None:
        """Play the audio stimulus in a background thread."""
        logger.info(
            "AUDIO STIM #%d (%s) ch=%d t=%.3fs",
            self._stim_count,
            event.event_type.name,
            event.channel_id,
            event.timestamp,
        )

        if self._audio_data is None:
            logger.warning("No audio data loaded — skipping playback")
            return

        if not self._sa_available:
            return

        # Play in background thread to avoid blocking the pipeline
        def _do_play():
            try:
                import simpleaudio as sa
                play_obj = sa.play_buffer(
                    self._audio_data,
                    num_channels=self._n_channels,
                    bytes_per_sample=self._sample_width,
                    sample_rate=self._sample_rate,
                )
                # Don't wait — let it play asynchronously
            except Exception:
                logger.exception("Audio playback failed")

        thread = threading.Thread(target=_do_play, daemon=True)
        thread.start()

    def reset(self) -> None:
        self._stim_count = 0