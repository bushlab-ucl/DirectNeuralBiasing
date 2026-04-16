"""Amplitude monitor — IED inhibition via broadband power.

Simple inhibition detector: bandpass the raw signal (e.g. 80–120 Hz),
compute RMS power, threshold it. If power exceeds threshold, set
active=True to block stimulation.

Baseline handling (v2 — drift-resistant):
    The adaptive baseline previously suffered from drift: detected IEDs
    got added to the running history, which inflated both the mean and
    (especially) the std, causing the threshold to creep upward over
    time until subsequent IEDs no longer tripped it.

    Fix: chunks flagged as 'active' are excluded from the baseline
    history. Only non-IED chunks contribute. Baseline stays stable
    regardless of IED density.
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.signal import butter, sosfilt

from dnb.core.types import PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class AmplitudeMonitor(Module):
    """Broadband power monitor for IED detection / stimulus inhibition.

    Bandpasses the signal into a target band (default 80–120 Hz),
    computes RMS power, flags chunks where it exceeds threshold.

    Adaptive mode uses `mean + n_std * std` of recent *non-active* chunks.
    Active chunks are excluded from the baseline to prevent drift.

    Args:
        id: Unique identifier for this detector.
        freq_range: (low_hz, high_hz) bandpass range.
        threshold: Absolute RMS power threshold. None = adaptive.
        adaptive_n_std: Stds above baseline mean for adaptive mode.
        warmup_chunks: Initial chunks to accumulate baseline.
        baseline_chunks: Number of recent non-active chunks tracked.
        filter_order: Butterworth filter order.
    """

    def __init__(
        self,
        id: str = "ied_monitor",
        freq_range: tuple[float, float] = (80.0, 120.0),
        threshold: float | None = None,
        adaptive_n_std: float = 3.0,
        warmup_chunks: int = 20,
        baseline_chunks: int = 100,
        filter_order: int = 4,
    ) -> None:
        self.id = id
        self._freq_range = freq_range
        self._threshold = threshold
        self._adaptive_n_std = adaptive_n_std
        self._warmup_chunks = warmup_chunks
        self._baseline_chunks = baseline_chunks
        self._filter_order = filter_order

        self._sos: np.ndarray | None = None
        self._chunks_seen: int = 0
        self._power_history: list[float] = []

    def configure(self, config: PipelineConfig) -> None:
        nyq = config.sample_rate / 2.0
        lo = self._freq_range[0] / nyq
        hi = self._freq_range[1] / nyq

        if hi >= 1.0:
            logger.warning(
                "AmplitudeMonitor '%s': upper freq %.1f Hz >= Nyquist %.1f Hz, "
                "clamping to 0.99*Nyquist",
                self.id, self._freq_range[1], nyq,
            )
            hi = 0.99

        if lo <= 0.0:
            lo = 0.001

        self._sos = butter(self._filter_order, [lo, hi], btype="band", output="sos")

        mode = "absolute" if self._threshold is not None else f"adaptive ({self._adaptive_n_std}σ)"
        logger.info(
            "AmplitudeMonitor '%s': freq=(%.1f, %.1f) Hz, mode=%s, "
            "warmup=%d chunks",
            self.id, self._freq_range[0], self._freq_range[1],
            mode, self._warmup_chunks,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        if self._sos is None:
            result.detections[self.id] = {"active": False, "power": 0.0}
            return result

        chunk = result.chunk

        filtered = sosfilt(self._sos, chunk.samples, axis=1)
        power = float(np.sqrt(np.mean(filtered ** 2)))

        self._chunks_seen += 1

        # Warmup — accumulate baseline, don't flag
        if self._chunks_seen <= self._warmup_chunks:
            self._power_history.append(power)
            if len(self._power_history) > self._baseline_chunks:
                self._power_history = self._power_history[-self._baseline_chunks:]
            result.detections[self.id] = {
                "active": False, "power": power, "warming_up": True,
            }
            return result

        # Compare against baseline from previous non-active chunks.
        if self._threshold is not None:
            active = power > self._threshold
        else:
            if len(self._power_history) == 0:
                active = False
            else:
                hist = np.array(self._power_history)
                baseline_mean = float(np.mean(hist))
                baseline_std = float(np.std(hist))
                adaptive_thresh = baseline_mean + self._adaptive_n_std * baseline_std
                active = power > adaptive_thresh

        # Drift fix: only add to history if NOT active.
        # IED chunks don't contaminate the baseline.
        if not active:
            self._power_history.append(power)
            if len(self._power_history) > self._baseline_chunks:
                self._power_history = self._power_history[-self._baseline_chunks:]

        result.detections[self.id] = {"active": active, "power": power}
        return result

    def reset(self) -> None:
        self._chunks_seen = 0
        self._power_history.clear()