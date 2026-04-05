"""Abstract base class for processing modules.

Modules are the composable units of the DNB pipeline. Each module
receives a DataChunk (or WaveletResult) and produces a ProcessResult
containing transformed data and optionally detected events.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from dnb.core.types import DataChunk, Event, PipelineConfig, WaveletResult

if TYPE_CHECKING:
    from dnb.core.ring_buffer import RingBuffer


@dataclass
class ProcessResult:
    """Output of a module's process() call.

    Attributes:
        chunk: The (possibly transformed) data chunk.
        wavelet: Wavelet decomposition, if computed by this module.
        events: Any events detected during processing.
        data: Arbitrary named arrays for downstream modules.
        ring_buffer: Reference to the pipeline's ring buffer, allowing
            modules to read historical samples for overlap/context.
            Note: if a Downsampler is in the chain, this is swapped to
            the Downsampler's internal ring buffer (at the downsampled
            rate) so that overlap-save works correctly.
        original_sample_rate: If the signal has been downsampled, this
            holds the original (pre-decimation) sample rate.  None if
            no resampling has occurred.
    """

    chunk: DataChunk
    wavelet: WaveletResult | None = None
    events: list[Event] = field(default_factory=list)
    data: dict[str, NDArray[np.float64]] = field(default_factory=dict)
    ring_buffer: RingBuffer | None = None
    original_sample_rate: float | None = None


class Module(ABC):
    """Abstract base for pipeline processing modules.

    Lifecycle: configure() is called once when the pipeline starts,
    then process() is called for every chunk.
    """

    @abstractmethod
    def configure(self, config: PipelineConfig) -> None:
        """One-time setup with pipeline configuration.

        Use this to pre-compute wavelet kernels, allocate state buffers, etc.
        """

    @abstractmethod
    def process(self, result: ProcessResult) -> ProcessResult:
        """Process a chunk and return the result.

        Modules form a chain: each module receives the ProcessResult from
        the previous module (or a fresh one wrapping the source chunk).

        Args:
            result: Output from the previous module in the chain.

        Returns:
            Updated ProcessResult, potentially with new wavelet data,
            events, or transformed chunk.
        """

    def reset(self) -> None:
        """Reset internal state (e.g. between runs). Override if stateful."""
