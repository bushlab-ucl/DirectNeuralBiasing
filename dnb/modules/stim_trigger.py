"""N-pulse stimulation trigger.

Detects a single slow wave via the activation detector, logs a
SLOW_WAVE event, then fires n audio stimulations starting at the
detected upwave and continuing at predicted future positive peaks.

    n_pulses=0  →  detection only: emit SLOW_WAVE, no STIM events
    n_pulses=1  →  detect, emit SLOW_WAVE + 1 STIM immediately
                   (at the detected upwave)
    n_pulses=3  →  detect, emit SLOW_WAVE + STIM immediately,
                   then 2 more STIMs at t0 + 1/freq, t0 + 2/freq

The first stim fires at the detection itself (the current upwave).
Additional stims are scheduled at predicted future peaks using the
detected frequency.

STIM events carry metadata:
    pulse_index: 1-indexed (1 = immediate stim, 2 = next peak, ...)
    n_pulses: total scheduled
    frequency: detected SW frequency used for scheduling
    detection_time: timestamp of the SLOW_WAVE detection

Inhibition: if the IED monitor is active, cancel all pending stims
and start a cooldown period.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from dnb.core.types import Event, EventType, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


@dataclass
class _PulseSchedule:
    """Pending pulse schedule for one channel."""
    stim_times: list[float]         # scheduled stim timestamps (1-indexed)
    frequency: float                # detected SW frequency
    detection_time: float           # time of the SLOW_WAVE detection
    next_idx: int = 0               # index into stim_times for next to emit


class StimTrigger(Module):
    """N-pulse trigger combining activation and inhibition detectors.

    Args:
        activation_detector_id: ID of the detector providing candidates.
        inhibition_detector_id: ID of the inhibition detector (or None).
        n_pulses: Number of stimulation pulses per detection (0=none).
        backoff_s: Minimum seconds between detection sequences.
        inhibition_cooldown_s: Seconds to wait after inhibition before
            allowing new detections.
    """

    def __init__(
        self,
        activation_detector_id: str = "slow_wave",
        inhibition_detector_id: str | None = "ied_monitor",
        n_pulses: int = 1,
        backoff_s: float = 5.0,
        inhibition_cooldown_s: float = 5.0,
    ) -> None:
        self._act_id = activation_detector_id
        self._inh_id = inhibition_detector_id
        self._n_pulses = n_pulses
        self._backoff_s = backoff_s
        self._inhibition_cooldown_s = inhibition_cooldown_s

        # Per-channel state
        self._last_detection_time: dict[int, float] = {}
        self._last_inhibition_time: dict[int, float] = {}
        self._schedules: dict[int, _PulseSchedule] = {}

    def configure(self, config: PipelineConfig) -> None:
        logger.info(
            "StimTrigger: activation='%s', inhibition='%s', "
            "n_pulses=%d, backoff=%.1fs",
            self._act_id, self._inh_id or "none",
            self._n_pulses, self._backoff_s,
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
            # Set cooldown for all channels in this chunk — even if no
            # candidates are present yet. This ensures an IED arriving
            # before a SW still blocks the upcoming detection.
            for ch_id in result.chunk.channel_ids:
                self._last_inhibition_time[int(ch_id)] = chunk_time

        # --- Emit scheduled stims whose time has arrived ---
        for ch_id in list(self._schedules):
            sched = self._schedules[ch_id]
            while sched.next_idx < len(sched.stim_times):
                t = sched.stim_times[sched.next_idx]
                if t > chunk_time:
                    break  # not yet
                pulse_num = sched.next_idx + 2  # pulse 1 already emitted
                events.append(Event(
                    event_type=EventType.STIM,
                    timestamp=t,
                    channel_id=ch_id,
                    metadata={
                        "pulse_index": pulse_num,
                        "n_pulses": self._n_pulses,
                        "frequency": sched.frequency,
                        "detection_time": sched.detection_time,
                    },
                ))
                logger.info(
                    "STIM %d/%d ch=%d t=%.3fs (freq=%.2f Hz)",
                    pulse_num, self._n_pulses, ch_id, t, sched.frequency,
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
            t0 = c["timestamp"]
            freq = c["frequency"]
            self._last_detection_time[ch_id] = t0

            # Always emit a SLOW_WAVE event for the detection
            events.append(Event(
                event_type=EventType.SLOW_WAVE,
                timestamp=t0,
                channel_id=ch_id,
                metadata={
                    "phase": c.get("phase", 0.0),
                    "frequency": freq,
                    "amplitude": c.get("amplitude", 0.0),
                    "n_pulses": self._n_pulses,
                },
            ))
            logger.info(
                "SLOW_WAVE detected ch=%d t=%.3fs freq=%.2f Hz amp=%.1f → %d stim(s)",
                ch_id, t0, freq, c.get("amplitude", 0), self._n_pulses,
            )

            # Schedule stims: k=0 at detection (immediate), k=1.. at future peaks
            if self._n_pulses > 0 and freq > 0:
                period = 1.0 / freq

                # Pulse 1 fires immediately at the detected upwave
                events.append(Event(
                    event_type=EventType.STIM,
                    timestamp=t0,
                    channel_id=ch_id,
                    metadata={
                        "pulse_index": 1,
                        "n_pulses": self._n_pulses,
                        "frequency": freq,
                        "detection_time": t0,
                    },
                ))
                logger.info(
                    "STIM 1/%d ch=%d t=%.3fs (immediate)",
                    self._n_pulses, ch_id, t0,
                )

                # Pulses 2..n at predicted future peaks
                if self._n_pulses > 1:
                    stim_times = [t0 + k * period for k in range(1, self._n_pulses)]
                    self._schedules[ch_id] = _PulseSchedule(
                        stim_times=stim_times,
                        frequency=freq,
                        detection_time=t0,
                        next_idx=0,
                    )

        result.events.extend(events)
        return result

    def reset(self) -> None:
        self._last_detection_time.clear()
        self._last_inhibition_time.clear()
        self._schedules.clear()