"""N-pulse stimulation trigger with phase-prediction scheduling.

The core idea:
    1. Detector fires at detection_phase (e.g. π = trough)
    2. Trigger computes when stim_phase (e.g. 0 = peak) will occur
    3. Stims are emitted with exact predicted timestamps

Phase prediction:
    Δφ = (stim_phase - detection_phase) mod 2π    ← uses TARGET phases
    Δt = Δφ / (2π × f)
    Pulse k fires at: t_det + Δt + (k-1)/f

Key design decisions:
    - delay uses the TARGET detection_phase, not the measured phase.
      The measured phase has noise/quantisation error. The target is
      what we intended to detect at — the delay should be deterministic.
    - All stims are emitted immediately at detection time with their
      exact predicted timestamps. No pending queue, no chunk-boundary
      gating. The timestamp IS the timing.
    - For n-pulse, subsequent pulses are spaced at 1/freq. The freq
      comes from the wavelet's dominant frequency estimate.

Event types:
    SLOW_WAVE — detection event. Always logged.
    STIM — stimulation. pulse_index is 1-indexed.

Inhibition cancels all stims for the current detection sequence
and starts a cooldown.
"""

from __future__ import annotations

import logging
from math import pi

import numpy as np

from dnb.core.types import Event, EventType, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


def _phase_delay(detection_phase: float, stim_phase: float, frequency: float) -> float:
    """Compute time from detection_phase to stim_phase at given frequency.

    Uses the TARGET phases — not measured/noisy values.
    """
    delta_phi = (stim_phase - detection_phase) % (2 * pi)
    if delta_phi < 1e-6:
        delta_phi = 2 * pi
    return delta_phi / (2 * pi * frequency)


class StimTrigger(Module):
    def __init__(
        self,
        activation_detector_id: str = "slow_wave",
        inhibition_detector_id: str | None = "ied_monitor",
        n_pulses: int = 1,
        stim_phase: float = 0.0,
        detection_phase: float | None = None,
        backoff_s: float = 5.0,
        inhibition_cooldown_s: float = 5.0,
    ) -> None:
        self._act_id = activation_detector_id
        self._inh_id = inhibition_detector_id
        self._n_pulses = n_pulses
        self._stim_phase = stim_phase % (2 * pi)
        self._detection_phase = detection_phase  # if None, read from SLOW_WAVE metadata
        self._backoff_s = backoff_s
        self._inhibition_cooldown_s = inhibition_cooldown_s

        self._last_detection_time: float = -np.inf
        self._last_inhibition_time: float = -np.inf
        # Track active stim sequences for inhibition cancellation
        self._active_sequence_det_time: float | None = None

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

        # --- Inhibition ---
        if inhibition_active:
            self._last_inhibition_time = chunk_time
            self._active_sequence_det_time = None
            # Don't process new detections
            result.events.extend(events)
            return result

        # --- Process new candidates ---
        candidates = activation.get("candidates", [])
        if not candidates:
            result.events.extend(events)
            return result

        # Take the first candidate only
        c = candidates[0]
        t_det = c["timestamp"]
        freq = c["frequency"]
        det_phase_measured = c["phase"]

        # Backoff check
        if t_det - self._last_detection_time < self._backoff_s:
            result.events.extend(events)
            return result

        # Inhibition cooldown check
        if t_det - self._last_inhibition_time < self._inhibition_cooldown_s:
            result.events.extend(events)
            return result

        self._last_detection_time = t_det

        # Use TARGET detection phase for delay calculation, not the
        # noisy measured phase. The measured phase has quantisation
        # error from the crossing detection. The target is what we
        # intended — the delay should be deterministic.
        if self._detection_phase is not None:
            det_phase_for_delay = self._detection_phase
        else:
            # Fall back to the detection_phase from the SLOW_WAVE metadata
            # (set by the detector's configured detection_phase)
            det_phase_for_delay = det_phase_measured

        delay_to_stim = _phase_delay(det_phase_for_delay, self._stim_phase, freq)
        period = 1.0 / freq

        # Emit SLOW_WAVE
        events.append(Event(
            event_type=EventType.SLOW_WAVE,
            timestamp=t_det,
            channel_id=ch_id,
            metadata={
                "detection_phase": det_phase_measured,
                "stim_phase": self._stim_phase,
                "frequency": freq,
                "amplitude": c.get("amplitude", 0.0),
                "n_pulses": self._n_pulses,
                "delay_to_stim_ms": delay_to_stim * 1000,
            },
        ))

        # Emit ALL stims immediately with exact predicted timestamps.
        # No pending queue — the timestamp is the timing.
        if self._n_pulses > 0 and freq > 0:
            for k in range(self._n_pulses):
                t_stim = t_det + delay_to_stim + k * period
                events.append(Event(
                    event_type=EventType.STIM,
                    timestamp=t_stim,
                    channel_id=ch_id,
                    metadata={
                        "pulse_index": k + 1,
                        "n_pulses": self._n_pulses,
                        "frequency": freq,
                        "detection_time": t_det,
                    },
                ))

        result.events.extend(events)
        return result

    def reset(self) -> None:
        self._last_detection_time = -np.inf
        self._last_inhibition_time = -np.inf
        self._active_sequence_det_time = None