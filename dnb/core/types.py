"""Shared data types for the DNB pipeline.

Single-channel throughout. The source selects one hardware channel;
everything downstream is 1D.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import numpy as np
from numpy.typing import NDArray


class EventType(Enum):
    STIM = auto()
    SLOW_WAVE = auto()
    IED = auto()
    CUSTOM = auto()


@dataclass(frozen=True, slots=True)
class DataChunk:
    """A block of continuous neural data — single channel.

    samples: 1D array, shape (n_samples,).
    """
    samples: NDArray[np.float64]
    timestamps: NDArray[np.float64]
    channel_id: int
    sample_rate: float

    @property
    def n_samples(self) -> int:
        return self.samples.shape[0]

    @property
    def duration(self) -> float:
        return self.n_samples / self.sample_rate


@dataclass(frozen=True, slots=True)
class WaveletResult:
    """Output of wavelet convolution — single channel.

    analytic: shape (n_freqs, n_samples).
    """
    analytic: NDArray[np.complex128]
    frequencies: NDArray[np.float64]
    chunk: DataChunk

    @property
    def amplitude(self) -> NDArray[np.float64]:
        return np.abs(self.analytic)

    @property
    def phase(self) -> NDArray[np.float64]:
        return np.angle(self.analytic)


@dataclass(frozen=True, slots=True)
class Event:
    event_type: EventType
    timestamp: float
    channel_id: int
    duration: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineConfig:
    """Pipeline configuration — single channel.

    sample_rate: hardware rate (before downsampling).
    channel_id: which hardware channel to read.
    """
    sample_rate: float = 30_000.0
    channel_id: int = 0
    buffer_duration: float = 10.0
    chunk_duration: float = 0.5

    @property
    def buffer_samples(self) -> int:
        return int(self.buffer_duration * self.sample_rate)

    @property
    def chunk_samples(self) -> int:
        return int(self.chunk_duration * self.sample_rate)