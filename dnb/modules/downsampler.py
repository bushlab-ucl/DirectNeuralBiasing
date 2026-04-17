"""Downsampler — decimates hardware rate to analysis rate.

Transforms the chunk. Does NOT write to the ring buffer —
the pipeline owns all ring buffer writes. This eliminates
double-write bugs.
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.signal import decimate

from dnb.core.types import DataChunk, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class Downsampler(Module):
    def __init__(self, target_rate: float = 500.0) -> None:
        self._target_rate = target_rate
        self._factor: int = 1
        self._actual_rate: float = 0.0

    @property
    def factor(self) -> int:
        return self._factor

    @property
    def actual_rate(self) -> float:
        return self._actual_rate

    def configure(self, config: PipelineConfig) -> None:
        self._factor = max(1, int(round(config.sample_rate / self._target_rate)))
        self._actual_rate = config.sample_rate / self._factor
        logger.info(
            "Downsampler: %d Hz → %d Hz (factor %d)",
            int(config.sample_rate), int(self._actual_rate), self._factor,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        if self._factor <= 1:
            return result

        chunk = result.chunk
        decimated = decimate(chunk.samples, self._factor, ftype="iir", zero_phase=False)
        n_out = decimated.shape[0]
        t0 = chunk.timestamps[0]
        timestamps = t0 + np.arange(n_out) / self._actual_rate

        result.original_sample_rate = chunk.sample_rate
        result.chunk = DataChunk(
            samples=decimated,
            timestamps=timestamps,
            channel_id=chunk.channel_id,
            sample_rate=self._actual_rate,
        )
        return result

    def reset(self) -> None:
        pass