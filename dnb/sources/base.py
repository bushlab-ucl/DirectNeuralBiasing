"""Abstract base class for all data sources."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dnb.core.types import DataChunk, PipelineConfig


class DataSource(ABC):
    @abstractmethod
    def connect(self, config: PipelineConfig) -> None: ...

    @abstractmethod
    def read_chunk(self) -> DataChunk | None: ...

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> DataSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()