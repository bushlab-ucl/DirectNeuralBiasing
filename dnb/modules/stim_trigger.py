"""Stimulation trigger for TWave-style detection.

Simplified from the original StimTrigger. The TWaveDetector already
provides candidates with exact predicted timestamps (detection_time + dt),
so this module doesn't need to compute phase delays.

It still handles:
    - Backoff (minimum gap between stim sequences)
    - Inhibition (from AmplitudeMonitor or similar)
    - Inhibition cooldown
    - N-pulse scheduling (multiple stims at successive predicted peaks)
"""

from __future__ import annotations

import logging
from math import pi

import numpy as np

from dnb.core.types import Event, EventType, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class StimTrigger(Module):
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

        self._last_detection_time: float = -np.inf
        self._last_inhibition_time: float = -np.inf

    def configure(self, config: PipelineConfig) -> None:
        logger.info(
            "StimTrigger: act='%s', inh='%s', n_pulses=%d, backoff=%.1fs",
            self._act_id, self._inh_id or "none",
            self._n_pulses, self._backoff_s,
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
            result.events.extend(events)
            return result

        # --- Process candidates ---
        candidates = activation.get("candidates", [])
        if not candidates:
            result.events.extend(events)
            return result

        c = candidates[0]
        t_stim = c["timestamp"]       # already the predicted stim time
        freq = c["frequency"]
        amplitude = c["amplitude"]
        t_now = chunk_time

        # Backoff check (based on current time, not predicted time)
        if t_now - self._last_detection_time < self._backoff_s:
            result.events.extend(events)
            return result

        # Inhibition cooldown check
        if t_now - self._last_inhibition_time < self._inhibition_cooldown_s:
            result.events.extend(events)
            return result

        self._last_detection_time = t_now
        period = 1.0 / freq if freq > 0 else 1.0

        # Emit SLOW_WAVE event (detection happened now, stim is predicted)
        events.append(Event(
            event_type=EventType.SLOW_WAVE,
            timestamp=t_now,
            channel_id=ch_id,
            metadata={
                "frequency": freq,
                "amplitude": amplitude,
                "phase_now": c.get("phase_now", 0.0),
                "dt_to_stim_ms": c.get("dt_to_target_ms", 0.0),
                "n_pulses": self._n_pulses,
            },
        ))

        # Emit stim events with exact predicted timestamps
        if self._n_pulses > 0 and freq > 0:
            for k in range(self._n_pulses):
                events.append(Event(
                    event_type=EventType.STIM,
                    timestamp=t_stim + k * period,
                    channel_id=ch_id,
                    metadata={
                        "pulse_index": k + 1,
                        "n_pulses": self._n_pulses,
                        "frequency": freq,
                        "detection_time": t_now,
                    },
                ))

        result.events.extend(events)
        return result

    def reset(self) -> None:
        self._last_detection_time = -np.inf
        self._last_inhibition_time = -np.inf