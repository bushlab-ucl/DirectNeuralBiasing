"""Abstract base class for all data sources.

Every source — hardware, simulator, file — implements this interface.
The pipeline doesn't care where data comes from, only that it arrives
as DataChunks through read_chunk().
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from dnb.core.types import DataChunk, PipelineConfig


class DataSource(ABC):
    """Abstract base for neural data sources.

    Lifecycle: connect() → read_chunk() (repeated) → close()

    Subclasses must implement all three methods. The source is also usable
    as a context manager which calls connect/close automatically.
    """

    @abstractmethod
    def connect(self, config: PipelineConfig) -> None:
        """Establish connection to the data source.

        Args:
            config: Pipeline configuration (sample rate, channels, etc.).
        """

    @abstractmethod
    def read_chunk(self) -> DataChunk | None:
        """Read the next chunk of data.

        For live sources, this blocks until data is available.
        For file sources, this returns None when the file is exhausted.

        Returns:
            A DataChunk, or None if the source is exhausted.
        """

    @abstractmethod
    def close(self) -> None:
        """Release resources and disconnect."""

    def __enter__(self) -> DataSource:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()