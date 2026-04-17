"""Threaded stim scheduler for live closed-loop operation.

Receives STIM events with exact predicted timestamps, sleeps until
each stim time using perf_counter, fires audio.
"""

from __future__ import annotations

import logging
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from dnb.core.types import Event, EventType

logger = logging.getLogger(__name__)


class StimScheduler:
    def __init__(
        self,
        wav_path: str | Path | None = None,
        volume: float = 1.0,
        on_fire: Callable[[Event, float, float], None] | None = None,
    ) -> None:
        self._wav_path = Path(wav_path) if wav_path else None
        self._volume = max(0.0, min(1.0, volume))
        self._on_fire = on_fire

        self._audio_data: np.ndarray | None = None
        self._sample_rate: int = 0
        self._n_channels: int = 0
        self._sample_width: int = 0
        self._sa_available = False

        self._pending: list[tuple[float, Event]] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._stim_count = 0
        self._time_offset: float | None = None

        self._load_audio()

    def _load_audio(self) -> None:
        if self._wav_path is None or not self._wav_path.exists():
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

        try:
            import simpleaudio
            self._sa_available = True
        except ImportError:
            self._sa_available = False

    def set_time_offset(self, pipeline_time: float, real_time: float) -> None:
        self._time_offset = real_time - pipeline_time

    def _to_real(self, pipeline_time: float) -> float:
        if self._time_offset is None:
            return pipeline_time
        return pipeline_time + self._time_offset

    def on_stim_event(self, event: Event) -> None:
        if event.event_type != EventType.STIM:
            return
        real_time = self._to_real(event.timestamp)
        with self._lock:
            self._pending.append((real_time, event))
            self._pending.sort(key=lambda x: x[0])

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="StimScheduler")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("StimScheduler stopped (%d stims fired)", self._stim_count)

    def _run(self) -> None:
        while self._running:
            event_to_fire = None
            with self._lock:
                if self._pending:
                    next_time, next_event = self._pending[0]
                    if time.perf_counter() >= next_time - 0.001:
                        event_to_fire = self._pending.pop(0)

            if event_to_fire is not None:
                target_time, event = event_to_fire
                while time.perf_counter() < target_time:
                    pass
                self._fire(event, target_time)
            else:
                time.sleep(0.0005)

    def _fire(self, event: Event, target_time: float) -> None:
        actual_time = time.perf_counter()
        jitter_ms = (actual_time - target_time) * 1000
        self._stim_count += 1

        pulse_idx = event.metadata.get("pulse_index", 0)
        logger.info("STIM #%d pulse=%d t=%.3fs jitter=%.1fms",
                     self._stim_count, pulse_idx, event.timestamp, jitter_ms)

        if self._on_fire:
            self._on_fire(event, actual_time, jitter_ms)

        if self._audio_data is not None and self._sa_available:
            try:
                import simpleaudio as sa
                sa.play_buffer(self._audio_data, self._n_channels,
                               self._sample_width, self._sample_rate)
            except Exception:
                logger.exception("Audio playback failed")

    @property
    def stim_count(self) -> int:
        return self._stim_count