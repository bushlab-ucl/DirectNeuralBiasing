"""Abstract base class for processing modules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from dnb.core.types import DataChunk, Event, PipelineConfig, WaveletResult

if TYPE_CHECKING:
    from dnb.core.ring_buffer import RingBuffer


@dataclass
class ProcessResult:
    """Output of a module's process() call.

    chunk: single-channel DataChunk (samples is 1D).
    """
    chunk: DataChunk | None
    wavelet: WaveletResult | None = None
    wavelet_settled: bool = False
    events: list[Event] = field(default_factory=list)
    detections: dict[str, dict] = field(default_factory=dict)
    ring_buffer: RingBuffer | None = None
    original_sample_rate: float | None = None


class Module(ABC):
    @abstractmethod
    def configure(self, config: PipelineConfig) -> None: ...

    @abstractmethod
    def process(self, result: ProcessResult) -> ProcessResult: ...

    def reset(self) -> None: ...