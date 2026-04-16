"""N-pulse stimulation trigger with phase-prediction scheduling.

The core idea:
    1. The detector fires at detection_phase (e.g. π = trough)
    2. This trigger computes when stim_phase (e.g. 0 = positive peak)
       will occur, using the detected frequency
    3. Stims are scheduled at predicted future times

Phase prediction:
    Given detection at phase φ_det with frequency f, the time until
    stim_phase φ_stim is:

        Δφ = (φ_stim - φ_det) mod 2π
        Δt = Δφ / (2π × f)

    Pulse k (0-indexed) fires at:  t_det + Δt + k/f

    So if we detect at the trough (π) and want to stim at the peak (0):
        Δφ = (0 - π) mod 2π = π
        Δt = π / (2π × f) = 1/(2f) = half a period

    This gives us half a period of lead time to schedule the stim.

Event types:
    SLOW_WAVE — detection event. Always logged. Carries detection metadata.
    STIM — scheduled stimulation. pulse_index is 1-indexed.
           Pulse 1 is the first predicted peak after detection.

Inhibition: if the IED monitor is active, cancel all pending stims
and start a cooldown period.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from math import pi

import numpy as np

from dnb.core.types import Event, EventType, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


def _phase_delay(detection_phase: float, stim_phase: float, frequency: float) -> float:
    """Compute time from detection_phase to stim_phase at given frequency.

    Returns delay in seconds. Always positive (wraps around the cycle).
    """
    delta_phi = (stim_phase - detection_phase) % (2 * pi)
    if delta_phi < 1e-6:
        # Same phase — schedule one full period ahead
        delta_phi = 2 * pi
    return delta_phi / (2 * pi * frequency)


@dataclass
class _PulseSchedule:
    """Pending pulse schedule for one channel."""
    stim_times: list[float]         # scheduled stim timestamps
    frequency: float                # detected SW frequency
    detection_time: float           # time of the SLOW_WAVE detection
    n_pulses: int                   # total pulses scheduled
    next_idx: int = 0               # index into stim_times for next to emit


class StimTrigger(Module):
    """N-pulse trigger with phase-prediction scheduling.

    Detects slow waves via the activation detector (at detection_phase),
    predicts when stim_phase will occur, and schedules n_pulses stims
    at predicted positive peaks.

    Args:
        activation_detector_id: ID of the detector providing candidates.
        inhibition_detector_id: ID of the inhibition detector (or None).
        n_pulses: Number of stimulation pulses per detection (0=none).
        stim_phase: Phase at which to stimulate (radians, default 0 = peak).
        backoff_s: Minimum seconds between detection sequences.
        inhibition_cooldown_s: Seconds to wait after inhibition before
            allowing new detections.
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

        # Per-channel state
        self._last_detection_time: dict[int, float] = {}
        self._last_inhibition_time: dict[int, float] = {}
        self._schedules: dict[int, _PulseSchedule] = {}

    def configure(self, config: PipelineConfig) -> None:
        logger.info(
            "StimTrigger: activation='%s', inhibition='%s', "
            "n_pulses=%d, stim_phase=%.2f rad (%.0f°), backoff=%.1fs",
            self._act_id, self._inh_id or "none",
            self._n_pulses, self._stim_phase,
            self._stim_phase * 180 / pi, self._backoff_s,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        activation = result.detections.get(self._act_id, {})
        inhibition = result.detections.get(self._inh_id, {}) if self._inh_id else {}

        inhibition_active = inhibition.get("active", False)
        candidates = activation.get("candidates", [])
        chunk_time = result.chunk.timestamps[-1] if result.chunk.n_samples > 0 else 0.0

        events: list[Event] = []

        # --- Handle inhibition: cancel pending schedules, start cooldown ---
        if inhibition_active:
            for ch_id in list(self._schedules):
                sched = self._schedules[ch_id]
                remaining = len(sched.stim_times) - sched.next_idx
                logger.info(
                    "Inhibition — cancelling %d pending stim(s) on ch=%d",
                    remaining, ch_id,
                )
                del self._schedules[ch_id]
            # Set cooldown for all channels in this chunk
            for ch_id in result.chunk.channel_ids:
                self._last_inhibition_time[int(ch_id)] = chunk_time

        # --- Emit scheduled stims whose time has arrived ---
        for ch_id in list(self._schedules):
            sched = self._schedules[ch_id]
            while sched.next_idx < len(sched.stim_times):
                t = sched.stim_times[sched.next_idx]
                if t > chunk_time:
                    break  # not yet
                pulse_num = sched.next_idx + 1
                events.append(Event(
                    event_type=EventType.STIM,
                    timestamp=t,
                    channel_id=ch_id,
                    metadata={
                        "pulse_index": pulse_num,
                        "n_pulses": sched.n_pulses,
                        "frequency": sched.frequency,
                        "detection_time": sched.detection_time,
                        "scheduled": True,
                    },
                ))
                logger.info(
                    "STIM %d/%d ch=%d t=%.3fs (scheduled, freq=%.2f Hz)",
                    pulse_num, sched.n_pulses, ch_id, t, sched.frequency,
                )
                sched.next_idx += 1

            # Clean up completed schedules
            if sched.next_idx >= len(sched.stim_times):
                del self._schedules[ch_id]

        # --- If inhibition is active, skip new detections ---
        if inhibition_active:
            result.events.extend(events)
            return result

        # --- Process new candidates ---
        seen_channels: set[int] = set()
        for c in candidates:
            ch_id = c["channel_id"]
            if ch_id in seen_channels:
                continue
            seen_channels.add(ch_id)

            # Already have a schedule running for this channel?
            if ch_id in self._schedules:
                continue

            # Backoff check
            last_det = self._last_detection_time.get(ch_id, -np.inf)
            if c["timestamp"] - last_det < self._backoff_s:
                continue

            # Inhibition cooldown check
            last_inh = self._last_inhibition_time.get(ch_id, -np.inf)
            if c["timestamp"] - last_inh < self._inhibition_cooldown_s:
                continue

            # --- New detection ---
            t_det = c["timestamp"]
            freq = c["frequency"]
            det_phase = c["phase"]
            self._last_detection_time[ch_id] = t_det

            # Compute time from detection to first stim (phase prediction)
            delay_to_stim = _phase_delay(det_phase, self._stim_phase, freq)
            period = 1.0 / freq

            # Always emit a SLOW_WAVE event at the detection time
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
            logger.info(
                "SLOW_WAVE ch=%d t=%.3fs det_phase=%.2f freq=%.2f Hz amp=%.1f "
                "→ %d stim(s), first in %.0fms",
                ch_id, t_det, det_phase, freq, c.get("amplitude", 0),
                self._n_pulses, delay_to_stim * 1000,
            )

            # Schedule stims at predicted future peak(s)
            if self._n_pulses > 0 and freq > 0:
                stim_times = [
                    t_det + delay_to_stim + k * period
                    for k in range(self._n_pulses)
                ]

                self._schedules[ch_id] = _PulseSchedule(
                    stim_times=stim_times,
                    frequency=freq,
                    detection_time=t_det,
                    n_pulses=self._n_pulses,
                    next_idx=0,
                )

                # Check if any stims are already due (within this chunk)
                sched = self._schedules[ch_id]
                while sched.next_idx < len(sched.stim_times):
                    t = sched.stim_times[sched.next_idx]
                    if t > chunk_time:
                        break
                    pulse_num = sched.next_idx + 1
                    events.append(Event(
                        event_type=EventType.STIM,
                        timestamp=t,
                        channel_id=ch_id,
                        metadata={
                            "pulse_index": pulse_num,
                            "n_pulses": self._n_pulses,
                            "frequency": freq,
                            "detection_time": t_det,
                            "scheduled": True,
                        },
                    ))
                    logger.info(
                        "STIM %d/%d ch=%d t=%.3fs (immediate, freq=%.2f Hz)",
                        pulse_num, self._n_pulses, ch_id, t, freq,
                    )
                    sched.next_idx += 1

                if sched.next_idx >= len(sched.stim_times):
                    del self._schedules[ch_id]

        result.events.extend(events)
        return result

    def reset(self) -> None:
        self._last_detection_time.clear()
        self._last_inhibition_time.clear()
        self._schedules.clear()