"""N-pulse stimulation trigger with phase-prediction scheduling.

The core idea:
    1. Detector fires at detection_phase (e.g. π = trough)
    2. Trigger computes when stim_phase (e.g. 0 = peak) will occur
    3. Stims are scheduled at predicted future times

Phase prediction:
    Δφ = (stim_phase - detection_phase) mod 2π
    Δt = Δφ / (2π × f)
    Pulse k fires at: t_det + Δt + (k-1)/f

Event types:
    SLOW_WAVE — detection event. Always logged.
    STIM — scheduled stimulation. pulse_index is 1-indexed.

Stim events carry the exact predicted timestamp, NOT quantised to
chunk boundaries. In offline mode this means a stim event's timestamp
may be in the future relative to the chunk that detected the slow wave.
The pipeline emits them immediately — timing accuracy is in the
timestamp, not in when the event object is created.

In live mode, the StimScheduler thread uses these timestamps to
fire audio at the right wall-clock time.
"""

from __future__ import annotations

import logging
from math import pi

import numpy as np

from dnb.core.types import Event, EventType, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


def _phase_delay(detection_phase: float, stim_phase: float, frequency: float) -> float:
    """Compute time from detection_phase to stim_phase at given frequency."""
    delta_phi = (stim_phase - detection_phase) % (2 * pi)
    if delta_phi < 1e-6:
        delta_phi = 2 * pi
    return delta_phi / (2 * pi * frequency)


class StimTrigger(Module):
    """N-pulse trigger with phase-prediction scheduling.

    Args:
        activation_detector_id: ID of the detector providing candidates.
        inhibition_detector_id: ID of the inhibition detector (or None).
        n_pulses: Number of stimulation pulses per detection (0=none).
        stim_phase: Phase at which to stimulate (radians).
        backoff_s: Minimum seconds between detection sequences.
        inhibition_cooldown_s: Seconds after inhibition before new detections.
    """

    def __init__(
        self,
        activation_detector_id: str = "slow_wave",
        inhibition_detector_id: str | None = "ied_monitor",
        n_pulses: int = 1,
        stim_phase: float = 0.0,
        backoff_s: float = 5.0,
        inhibition_cooldown_s: float = 5.0,
    ) -> None:
        self._act_id = activation_detector_id
        self._inh_id = inhibition_detector_id
        self._n_pulses = n_pulses
        self._stim_phase = stim_phase % (2 * pi)
        self._backoff_s = backoff_s
        self._inhibition_cooldown_s = inhibition_cooldown_s

        self._last_detection_time: float = -np.inf
        self._last_inhibition_time: float = -np.inf
        # Pending stim times that haven't been emitted yet
        self._pending_stims: list[tuple[float, int, float, float]] = []  # (time, pulse_idx, freq, det_time)

    def configure(self, config: PipelineConfig) -> None:
        logger.info(
            "StimTrigger: act='%s', inh='%s', n_pulses=%d, stim_phase=%.2f rad, backoff=%.1fs",
            self._act_id, self._inh_id or "none",
            self._n_pulses, self._stim_phase, self._backoff_s,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        activation = result.detections.get(self._act_id, {})
        inhibition = result.detections.get(self._inh_id, {}) if self._inh_id else {}
        inhibition_active = inhibition.get("active", False)

        chunk_time = result.chunk.timestamps[-1] if result.chunk.n_samples > 0 else 0.0
        ch_id = result.chunk.channel_id
        events: list[Event] = []

        # --- Inhibition: cancel all pending stims ---
        if inhibition_active:
            if self._pending_stims:
                logger.info("Inhibition — cancelling %d pending stim(s)", len(self._pending_stims))
                self._pending_stims.clear()
            self._last_inhibition_time = chunk_time

        # --- Emit any pending stims whose time has arrived ---
        # We emit ALL scheduled stims immediately with their exact timestamps.
        # In offline mode the timestamp IS the result — we don't wait for chunks.
        still_pending = []
        for (t_stim, pulse_idx, freq, det_time) in self._pending_stims:
            if t_stim <= chunk_time:
                events.append(Event(
                    event_type=EventType.STIM,
                    timestamp=t_stim,
                    channel_id=ch_id,
                    metadata={
                        "pulse_index": pulse_idx,
                        "n_pulses": self._n_pulses,
                        "frequency": freq,
                        "detection_time": det_time,
                        "scheduled": True,
                    },
                ))
            else:
                still_pending.append((t_stim, pulse_idx, freq, det_time))
        self._pending_stims = still_pending

        # --- Skip new detections if inhibited ---
        if inhibition_active:
            result.events.extend(events)
            return result

        # --- Process new candidates ---
        candidates = activation.get("candidates", [])
        if not candidates:
            result.events.extend(events)
            return result

        # Take the first candidate only (one detection per chunk)
        c = candidates[0]
        t_det = c["timestamp"]
        freq = c["frequency"]
        det_phase = c["phase"]

        # Backoff check
        if t_det - self._last_detection_time < self._backoff_s:
            result.events.extend(events)
            return result

        # Inhibition cooldown check
        if t_det - self._last_inhibition_time < self._inhibition_cooldown_s:
            result.events.extend(events)
            return result

        # Already have pending stims?
        if self._pending_stims:
            result.events.extend(events)
            return result

        self._last_detection_time = t_det

        # Phase prediction
        delay_to_stim = _phase_delay(det_phase, self._stim_phase, freq)
        period = 1.0 / freq

        # Always emit SLOW_WAVE
        events.append(Event(
            event_type=EventType.SLOW_WAVE,
            timestamp=t_det,
            channel_id=ch_id,
            metadata={
                "detection_phase": det_phase,
                "stim_phase": self._stim_phase,
                "frequency": freq,
                "amplitude": c.get("amplitude", 0.0),
                "n_pulses": self._n_pulses,
                "delay_to_stim_ms": delay_to_stim * 1000,
            },
        ))

        # Schedule stims at exact predicted times
        if self._n_pulses > 0 and freq > 0:
            for k in range(self._n_pulses):
                t_stim = t_det + delay_to_stim + k * period
                pulse_idx = k + 1

                if t_stim <= chunk_time:
                    # Already past — emit immediately
                    events.append(Event(
                        event_type=EventType.STIM,
                        timestamp=t_stim,
                        channel_id=ch_id,
                        metadata={
                            "pulse_index": pulse_idx,
                            "n_pulses": self._n_pulses,
                            "frequency": freq,
                            "detection_time": t_det,
                            "scheduled": True,
                        },
                    ))
                else:
                    # Future — add to pending
                    self._pending_stims.append((t_stim, pulse_idx, freq, t_det))

        result.events.extend(events)
        return result

    def reset(self) -> None:
        self._last_detection_time = -np.inf
        self._last_inhibition_time = -np.inf
        self._pending_stims.clear()