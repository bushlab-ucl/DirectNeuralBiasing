"""Downsampler module for efficient low-frequency processing.

Only needed when running at hardware rates (e.g. 30 kHz → 500 Hz).
Not needed for synthetic data at 1 kHz. Maintains its own ring buffer
at the downsampled rate so downstream overlap-save works correctly.
"""

from __future__ import annotations

import logging

import numpy as np
from scipy.signal import decimate

from dnb.core.ring_buffer import RingBuffer
from dnb.core.types import DataChunk, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class Downsampler(Module):
    """Decimate the signal to a lower sample rate.

    After processing, result.ring_buffer is swapped to an internal
    buffer at the downsampled rate.

    Args:
        target_rate: Desired output sample rate in Hz.
        buffer_duration: Internal ring buffer duration in seconds.
    """

    def __init__(self, target_rate: float = 500.0, buffer_duration: float = 10.0) -> None:
        self._target_rate = target_rate
        self._buffer_duration = buffer_duration
        self._factor: int = 1
        self._actual_rate: float = 0.0
        self._ds_ring: RingBuffer | None = None

    @property
    def factor(self) -> int:
        return self._factor

    @property
    def actual_rate(self) -> float:
        return self._actual_rate

    def configure(self, config: PipelineConfig) -> None:
        self._factor = max(1, int(round(config.sample_rate / self._target_rate)))
        self._actual_rate = config.sample_rate / self._factor
        ds_capacity = int(self._buffer_duration * self._actual_rate)
        self._ds_ring = RingBuffer(n_channels=config.n_channels, capacity=ds_capacity)
        logger.info(
            "Downsampler: %d Hz → %d Hz (factor %d)",
            int(config.sample_rate), int(self._actual_rate), self._factor,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        if self._factor <= 1:
            return result

        chunk = result.chunk
        decimated = np.stack([
            decimate(chunk.samples[ch], self._factor, ftype="iir", zero_phase=False)
            for ch in range(chunk.n_channels)
        ])

        n_out = decimated.shape[1]
        t0 = chunk.timestamps[0]
        timestamps = t0 + np.arange(n_out) / self._actual_rate

        new_chunk = DataChunk(
            samples=decimated, timestamps=timestamps,
            channel_ids=chunk.channel_ids, sample_rate=self._actual_rate,
        )

        if self._ds_ring is not None:
            self._ds_ring.write(decimated)
            result.ring_buffer = self._ds_ring

        result.original_sample_rate = chunk.sample_rate
        result.chunk = new_chunk
        return result

    def reset(self) -> None:
        if self._ds_ring is not None:
            self._ds_ring.clear()
