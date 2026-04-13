"""Shared data types for the DNB pipeline.

These types form the contract between all components: sources produce
DataChunks, modules consume and transform them via ProcessResults,
and events flow out through the EventBus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import numpy as np
from numpy.typing import NDArray


class EventType(Enum):
    """Categories of detected neural events."""
    STIM = auto()           # stimulation trigger (pulse_index in metadata)
    SLOW_WAVE = auto()      # slow wave candidate (from TargetWaveDetector)
    IED = auto()            # interictal epileptiform discharge
    CUSTOM = auto()


@dataclass(frozen=True, slots=True)
class DataChunk:
    """A block of continuous neural data from a source.

    Attributes:
        samples: Neural data, shape (n_channels, n_samples).
        timestamps: Per-sample timestamps in seconds, shape (n_samples,).
        channel_ids: Channel identifiers, shape (n_channels,).
        sample_rate: Sampling rate in Hz.
    """
    samples: NDArray[np.float64]
    timestamps: NDArray[np.float64]
    channel_ids: NDArray[np.int32]
    sample_rate: float

    @property
    def n_channels(self) -> int:
        return self.samples.shape[0]

    @property
    def n_samples(self) -> int:
        return self.samples.shape[1]

    @property
    def duration(self) -> float:
        return self.n_samples / self.sample_rate


@dataclass(frozen=True, slots=True)
class WaveletResult:
    """Output of wavelet convolution.

    Contains the full analytic signal at every (channel, frequency, time)
    point. Downstream modules read .amplitude, .phase, .power directly.

    Attributes:
        analytic: Complex analytic signal, shape (n_channels, n_freqs, n_samples).
        frequencies: Centre frequencies in Hz, shape (n_freqs,).
        chunk: The DataChunk this was computed from.
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

    @property
    def power(self) -> NDArray[np.float64]:
        return np.abs(self.analytic) ** 2


@dataclass(frozen=True, slots=True)
class Event:
    """A detected neural event.

    Attributes:
        event_type: Category of the event.
        timestamp: Time in seconds from recording start.
        channel_id: Channel on which the event was detected.
        duration: Duration in seconds (0 for point events).
        metadata: Arbitrary key-value data from the detecting module.
    """
    event_type: EventType
    timestamp: float
    channel_id: int
    duration: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineConfig:
    """Pipeline configuration.

    Attributes:
        sample_rate: Expected sample rate in Hz.
        n_channels: Number of channels.
        channel_ids: Explicit channel IDs (defaults to range(n_channels)).
        buffer_duration: Ring buffer length in seconds.
        chunk_duration: Processing chunk length in seconds.
    """
    sample_rate: float = 30_000.0
    n_channels: int = 1
    channel_ids: NDArray[np.int32] | None = None
    buffer_duration: float = 10.0
    chunk_duration: float = 0.5

    def __post_init__(self) -> None:
        if self.channel_ids is None:
            self.channel_ids = np.arange(self.n_channels, dtype=np.int32)

    @property
    def buffer_samples(self) -> int:
        return int(self.buffer_duration * self.sample_rate)

    @property
    def chunk_samples(self) -> int:
        return int(self.chunk_duration * self.sample_rate)