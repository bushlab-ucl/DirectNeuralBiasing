"""Threaded stim scheduler for live closed-loop operation.

In offline mode, stim timing is determined by chunk boundaries —
a STIM event is emitted when chunk_time passes the scheduled time.
This is fine for analysis but gives chunk_duration quantisation.

In live mode, we need sub-chunk precision. The StimScheduler runs
a daemon thread that:
    1. Receives scheduled stim times from the pipeline event bus
    2. Sleeps until each stim time (using perf_counter for precision)
    3. Fires the audio stimulus at the right moment
    4. Logs actual fire time for post-hoc analysis

The pipeline still emits STIM events at chunk boundaries for logging.
The scheduler handles the actual audio trigger independently.

Usage:
    scheduler = StimScheduler(wav_path="assets/pink_noise_short.wav")
    scheduler.start()
    pipeline.on_event("STIM", scheduler.on_stim_event)
    ...
    scheduler.stop()
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
    """Threaded audio stimulus scheduler for live operation.

    Receives STIM events from the pipeline, schedules audio playback
    at the predicted stim times with high-precision sleep.

    Args:
        wav_path: Path to stimulus WAV file.
        volume: Playback volume (0.0–1.0).
        pipeline_start_time: perf_counter value at pipeline start,
            used to convert pipeline timestamps to real time.
        on_fire: Optional callback when stim actually fires.
            Signature: (event, actual_time_s, jitter_ms) -> None
    """

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

        self._pending: list[tuple[float, Event]] = []  # (real_time, event)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._stim_count = 0

        # Mapping: pipeline_time → real_time
        # Set when the first chunk arrives so we can convert
        self._time_offset: float | None = None  # real_time - pipeline_time

        self._load_audio()

    def _load_audio(self) -> None:
        if self._wav_path is None or not self._wav_path.exists():
            if self._wav_path:
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
            logger.warning("simpleaudio not available — stims will be logged only")

    def set_time_offset(self, pipeline_time: float, real_time: float) -> None:
        """Set the mapping between pipeline timestamps and real time."""
        self._time_offset = real_time - pipeline_time

    def _pipeline_to_real(self, pipeline_time: float) -> float:
        """Convert pipeline timestamp to real perf_counter time."""
        if self._time_offset is None:
            # Fallback: assume pipeline started at perf_counter epoch
            return pipeline_time
        return pipeline_time + self._time_offset

    def on_stim_event(self, event: Event) -> None:
        """Called from pipeline event bus when a STIM event is emitted."""
        if event.event_type != EventType.STIM:
            return

        real_time = self._pipeline_to_real(event.timestamp)

        with self._lock:
            self._pending.append((real_time, event))
            # Keep sorted by time
            self._pending.sort(key=lambda x: x[0])

    def start(self) -> None:
        """Start the scheduler thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name="StimScheduler")
        self._thread.start()
        logger.info("StimScheduler started (audio=%s)", "yes" if self._sa_available else "log-only")

    def stop(self) -> None:
        """Stop the scheduler thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("StimScheduler stopped (%d stims fired)", self._stim_count)

    def _run(self) -> None:
        """Main scheduler loop — high-precision sleep until stim times."""
        while self._running:
            event_to_fire = None

            with self._lock:
                if self._pending:
                    next_time, next_event = self._pending[0]
                    now = time.perf_counter()
                    if now >= next_time - 0.001:  # 1ms tolerance
                        event_to_fire = self._pending.pop(0)

            if event_to_fire is not None:
                target_time, event = event_to_fire
                # Busy-wait for final precision (last 1ms)
                while time.perf_counter() < target_time:
                    pass
                self._fire(event, target_time)
            else:
                # Sleep briefly, wake up to check again
                time.sleep(0.0005)  # 0.5ms polling

    def _fire(self, event: Event, target_time: float) -> None:
        """Fire the audio stimulus."""
        actual_time = time.perf_counter()
        jitter_ms = (actual_time - target_time) * 1000
        self._stim_count += 1

        pulse_idx = event.metadata.get("pulse_index", 0)
        n_pulses = event.metadata.get("n_pulses", 1)
        logger.info(
            "AUDIO STIM #%d (%d/%d) t=%.3fs jitter=%.1fms",
            self._stim_count, pulse_idx, n_pulses,
            event.timestamp, jitter_ms,
        )

        if self._on_fire:
            self._on_fire(event, actual_time, jitter_ms)

        if self._audio_data is not None and self._sa_available:
            try:
                import simpleaudio as sa
                sa.play_buffer(
                    self._audio_data, self._n_channels,
                    self._sample_width, self._sample_rate,
                )
            except Exception:
                logger.exception("Audio playback failed")

    @property
    def stim_count(self) -> int:
        return self._stim_count

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)