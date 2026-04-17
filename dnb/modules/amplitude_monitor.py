"""Amplitude monitor — IED inhibition via broadband power, single channel.

Filter built lazily from actual chunk sample rate.
Rolling z-score baseline (Welford). Active chunks excluded from baseline.
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.signal import butter, sosfilt

from dnb.core.types import PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class _RollingStats:
    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self._m2 = 0.0

    def update(self, value: float) -> None:
        self.count += 1
        d = value - self.mean
        self.mean += d / self.count
        self._m2 += d * (value - self.mean)

    @property
    def std(self) -> float:
        return (self._m2 / self.count) ** 0.5 if self.count > 1 else 0.0

    def z_score(self, value: float) -> float:
        s = self.std
        return (value - self.mean) / s if s > 0 else 0.0


class AmplitudeMonitor(Module):
    def __init__(
        self,
        id: str = "ied_monitor",
        freq_range: tuple[float, float] = (80.0, 120.0),
        threshold: float | None = None,
        adaptive_n_std: float = 3.0,
        warmup_chunks: int = 20,
        filter_order: int = 4,
        baseline_chunks: int = 100,  # compat, ignored
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
        logger.info(
            "AmplitudeMonitor '%s': freq=(%.1f,%.1f), warmup=%d (filter built on first chunk)",
            self.id, *self._freq_range, self._warmup_chunks,
        )

    def _build_filter(self, sample_rate: float) -> None:
        nyq = sample_rate / 2.0
        lo = self._freq_range[0] / nyq
        hi = self._freq_range[1] / nyq
        if hi >= 1.0:
            hi = 0.99
        if lo <= 0.0:
            lo = 0.001
        if lo >= hi:
            logger.warning("AmplitudeMonitor '%s': invalid band at %.0f Hz — disabling", self.id, sample_rate)
            self._sos = None
            return
        self._sos = butter(self._filter_order, [lo, hi], btype="band", output="sos")
        self._built_for_rate = sample_rate
        logger.info("AmplitudeMonitor '%s': filter at %.0f Hz (band %.0f–%.0f Hz)",
                     self.id, sample_rate, self._freq_range[0], self._freq_range[1])

    def process(self, result: ProcessResult) -> ProcessResult:
        chunk = result.chunk
        if self._sos is None or abs(chunk.sample_rate - self._built_for_rate) > 0.1:
            self._build_filter(chunk.sample_rate)
        if self._sos is None:
            result.detections[self.id] = {"active": False, "power": 0.0}
            return result

        # 1D filter
        filtered = sosfilt(self._sos, chunk.samples)
        power = float(np.sqrt(np.mean(filtered ** 2)))
        self._chunks_seen += 1

        if self._chunks_seen <= self._warmup_chunks:
            self._stats.update(power)
            result.detections[self.id] = {"active": False, "power": power, "warming_up": True}
            return result

        if self._threshold is not None:
            active = power > self._threshold
        else:
            active = self._stats.z_score(power) > self._adaptive_n_std if self._stats.count > 0 else False

        if not active:
            self._stats.update(power)

        result.detections[self.id] = {"active": active, "power": power}
        return result

    def reset(self) -> None:
        self._chunks_seen = 0
        self._stats = _RollingStats()
        self._sos = None
        self._built_for_rate = 0.0