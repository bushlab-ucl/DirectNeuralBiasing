"""Amplitude monitor — IED inhibition via broadband power.

Simple inhibition detector: bandpass the raw signal (e.g. 80–120 Hz),
compute RMS power, threshold it. If power exceeds threshold, set
active=True to block stimulation.

Amplitude baseline uses a rolling z-score (matching the Rust
Statistics struct). Only non-active chunks contribute to the
baseline — IED chunks are excluded to prevent drift.

Filter construction is deferred to the first process() call so that
the actual post-downsample sample rate is used, not the hardware rate
from PipelineConfig.
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.signal import butter, sosfilt

from dnb.core.types import PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class _RollingStats:
    """Running mean/std tracker (mirrors Rust Statistics struct).

    Uses Welford's online algorithm for numerical stability.
    """

    def __init__(self) -> None:
        self.count: int = 0
        self.mean: float = 0.0
        self._m2: float = 0.0

    def update(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self._m2 += delta * delta2

    @property
    def std(self) -> float:
        if self.count < 2:
            return 0.0
        return (self._m2 / self.count) ** 0.5

    def z_score(self, value: float) -> float:
        s = self.std
        if s == 0.0:
            return 0.0
        return (value - self.mean) / s


class AmplitudeMonitor(Module):
    """Broadband power monitor for IED detection / stimulus inhibition.

    Bandpasses the signal into a target band (default 80–120 Hz),
    computes RMS power, flags chunks where it exceeds threshold.

    Filter is built lazily on first process() call using the actual
    chunk sample rate, so it works correctly whether a Downsampler
    is upstream or not.

    Adaptive mode uses a rolling z-score baseline (Welford's algorithm).
    Active chunks are excluded from the baseline to prevent drift.

    Args:
        id: Unique identifier for this detector.
        freq_range: (low_hz, high_hz) bandpass range.
        threshold: Absolute RMS power threshold. None = adaptive.
        adaptive_n_std: Stds above baseline mean for adaptive mode.
        warmup_chunks: Initial chunks to accumulate baseline.
        filter_order: Butterworth filter order.
    """

    def __init__(
        self,
        id: str = "ied_monitor",
        freq_range: tuple[float, float] = (80.0, 120.0),
        threshold: float | None = None,
        adaptive_n_std: float = 3.0,
        warmup_chunks: int = 20,
        filter_order: int = 4,
        # baseline_chunks kept for config compat but ignored — rolling stats don't window
        baseline_chunks: int = 100,
    ) -> None:
        self.id = id
        self._freq_range = freq_range
        self._threshold = threshold
        self._adaptive_n_std = adaptive_n_std
        self._warmup_chunks = warmup_chunks
        self._filter_order = filter_order

        self._sos: np.ndarray | None = None
        self._built_for_rate: float = 0.0
        self._chunks_seen: int = 0
        self._stats = _RollingStats()

    def configure(self, config: PipelineConfig) -> None:
        # Don't build filter here — we don't know the actual rate yet.
        # Filter is built lazily in process().
        mode = "absolute" if self._threshold is not None else f"adaptive ({self._adaptive_n_std}σ)"
        logger.info(
            "AmplitudeMonitor '%s': freq=(%.1f, %.1f) Hz, mode=%s, "
            "warmup=%d chunks (filter built on first chunk)",
            self.id, self._freq_range[0], self._freq_range[1],
            mode, self._warmup_chunks,
        )

    def _build_filter(self, sample_rate: float) -> None:
        """Build Butterworth bandpass for the actual sample rate."""
        nyq = sample_rate / 2.0
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

        if lo >= hi:
            logger.warning(
                "AmplitudeMonitor '%s': freq range (%.1f, %.1f) Hz invalid at "
                "%.0f Hz sample rate — disabling filter",
                self.id, self._freq_range[0], self._freq_range[1], sample_rate,
            )
            self._sos = None
            return

        self._sos = butter(self._filter_order, [lo, hi], btype="band", output="sos")
        self._built_for_rate = sample_rate
        logger.info(
            "AmplitudeMonitor '%s': filter built for %.0f Hz sample rate "
            "(Nyquist=%.0f Hz, band=%.1f–%.1f Hz)",
            self.id, sample_rate, nyq,
            self._freq_range[0], self._freq_range[1],
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        chunk = result.chunk

        # Lazy filter build on first chunk, or rebuild if rate changed
        if self._sos is None or abs(chunk.sample_rate - self._built_for_rate) > 0.1:
            self._build_filter(chunk.sample_rate)

        if self._sos is None:
            result.detections[self.id] = {"active": False, "power": 0.0}
            return result

        filtered = sosfilt(self._sos, chunk.samples, axis=1)
        power = float(np.sqrt(np.mean(filtered ** 2)))

        self._chunks_seen += 1

        # Warmup — accumulate baseline, don't flag
        if self._chunks_seen <= self._warmup_chunks:
            self._stats.update(power)
            result.detections[self.id] = {
                "active": False, "power": power, "warming_up": True,
            }
            return result

        # Compare against rolling baseline
        if self._threshold is not None:
            active = power > self._threshold
        else:
            if self._stats.count == 0:
                active = False
            else:
                z = self._stats.z_score(power)
                active = z > self._adaptive_n_std

        # Only add to baseline if NOT active (drift prevention)
        if not active:
            self._stats.update(power)

        result.detections[self.id] = {
            "active": active,
            "power": power,
            "z_score": self._stats.z_score(power) if self._stats.count > 0 else 0.0,
        }
        return result

    def reset(self) -> None:
        self._chunks_seen = 0
        self._stats = _RollingStats()
        self._sos = None
        self._built_for_rate = 0.0