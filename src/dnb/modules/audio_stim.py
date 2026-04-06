"""Audio stimulation module — plays a WAV file on STIM events."""

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
    """Play an audio stimulus on STIM events.

    Args:
        wav_path: Path to the WAV file.
        trigger_on: Which event types trigger playback.
        volume: Volume scaling (0.0 to 1.0).
    """

    def __init__(
        self,
        wav_path: str | Path,
        trigger_on: tuple[EventType, ...] = (EventType.STIM1,),
        volume: float = 1.0,
    ) -> None:
        self._wav_path = Path(wav_path)
        self._trigger_on = trigger_on
        self._volume = max(0.0, min(1.0, volume))
        self._audio_data: np.ndarray | None = None
        self._sample_rate: int = 0
        self._n_channels: int = 0
        self._sample_width: int = 0
        self._sa_available = False
        self._stim_count = 0

    def configure(self, config: PipelineConfig) -> None:
        if not self._wav_path.exists():
            logger.warning("Audio file not found: %s", self._wav_path)
            return

        try:
            with wave.open(str(self._wav_path), "rb") as wf:
                self._sample_rate = wf.getframerate()
                self._n_channels = wf.getnchannels()
                self._sample_width = wf.getsampwidth()
                raw = wf.readframes(wf.getnframes())
                self._audio_data = np.frombuffer(raw, dtype=np.int16).copy()
                if self._volume < 1.0:
                    scaled = self._audio_data.astype(np.float64) * self._volume
                    self._audio_data = scaled.clip(-32768, 32767).astype(np.int16)
        except Exception:
            logger.exception("Failed to load audio: %s", self._wav_path)
            return

        try:
            import simpleaudio  # noqa: F401
            self._sa_available = True
        except ImportError:
            self._sa_available = False
            logger.warning("simpleaudio not available — audio will be logged only")

    def process(self, result: ProcessResult) -> ProcessResult:
        for event in result.events:
            if event.event_type in self._trigger_on:
                self._stim_count += 1
                self._play(event)
        return result

    def _play(self, event: Event) -> None:
        logger.info("AUDIO STIM #%d (%s) t=%.3fs", self._stim_count, event.event_type.name, event.timestamp)
        if self._audio_data is None or not self._sa_available:
            return

        def _do_play():
            try:
                import simpleaudio as sa
                sa.play_buffer(self._audio_data, self._n_channels, self._sample_width, self._sample_rate)
            except Exception:
                logger.exception("Audio playback failed")

        threading.Thread(target=_do_play, daemon=True).start()

    def reset(self) -> None:
        self._stim_count = 0
