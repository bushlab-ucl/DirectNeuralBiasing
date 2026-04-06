"""Abstract base class for processing modules.

Modules follow the Rust architecture: they are composable, chainable
units. Each receives a ProcessResult and returns an updated one.

The pipeline pattern is:
    WaveletConvolution → [Detectors] → StimTrigger

Detectors set flags/candidates on the ProcessResult.
The StimTrigger reads those flags to decide whether to fire.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from dnb.core.types import DataChunk, Event, PipelineConfig, WaveletResult

if TYPE_CHECKING:
    from dnb.core.ring_buffer import RingBuffer


@dataclass
class ProcessResult:
    """Output of a module's process() call.

    Attributes:
        chunk: The (possibly resampled) data chunk.
        wavelet: Wavelet decomposition, if computed.
        events: Events detected so far in this chunk.
        detections: Named boolean/float flags set by detectors,
            read by the trigger module. Maps detector_id → per-sample
            or per-chunk data.
        ring_buffer: Reference to the pipeline's ring buffer.
        original_sample_rate: Pre-decimation rate, if downsampled.
    """
    chunk: DataChunk
    wavelet: WaveletResult | None = None
    events: list[Event] = field(default_factory=list)
    detections: dict[str, dict] = field(default_factory=dict)
    ring_buffer: RingBuffer | None = None
    original_sample_rate: float | None = None


class Module(ABC):
    """Abstract base for pipeline modules.

    Lifecycle: configure() once at startup, then process() per chunk.
    """

    @abstractmethod
    def configure(self, config: PipelineConfig) -> None:
        """One-time setup with pipeline configuration."""

    @abstractmethod
    def process(self, result: ProcessResult) -> ProcessResult:
        """Process a chunk. Return the updated ProcessResult."""

    def reset(self) -> None:
        """Reset internal state between runs. Override if stateful."""
