"""File data source — reads .npz files chunk by chunk."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from dnb.core.types import DataChunk, PipelineConfig
from dnb.sources.base import DataSource

logger = logging.getLogger(__name__)


class FileSource(DataSource):
    """Reads continuous data from a saved .npz file.

    Expected keys: 'continuous' (n_channels, n_samples), 'sample_rate'.
    Optional: 'channel_ids', 'timestamps'.

    After connect(), resolved_config holds the file's actual parameters.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._data: np.ndarray | None = None
        self._sample_rate: float = 0.0
        self._channel_ids: np.ndarray | None = None
        self._read_pos: int = 0
        self._total_samples: int = 0
        self._resolved_config: PipelineConfig | None = None

    @property
    def resolved_config(self) -> PipelineConfig | None:
        return self._resolved_config

    def connect(self, config: PipelineConfig) -> None:
        if not self._path.exists():
            raise FileNotFoundError(f"Data file not found: {self._path}")

        npz = np.load(str(self._path), allow_pickle=False)
        self._data = npz["continuous"].astype(np.float64)
        self._sample_rate = float(npz["sample_rate"])
        self._total_samples = self._data.shape[1]
        self._read_pos = 0
        self._channel_ids = (
            npz["channel_ids"].astype(np.int32)
            if "channel_ids" in npz
            else np.arange(self._data.shape[0], dtype=np.int32)
        )

        self._resolved_config = PipelineConfig(
            sample_rate=self._sample_rate,
            n_channels=self._data.shape[0],
            channel_ids=self._channel_ids,
            buffer_duration=config.buffer_duration,
            chunk_duration=config.chunk_duration,
        )
        logger.info(
            "FileSource: %s (%d ch, %.1fs @ %.0f Hz)",
            self._path.name, self._data.shape[0],
            self._total_samples / self._sample_rate, self._sample_rate,
        )

    def read_chunk(self) -> DataChunk | None:
        if self._data is None or self._resolved_config is None:
            raise RuntimeError("Source not connected.")
        if self._read_pos >= self._total_samples:
            return None

        chunk_size = self._resolved_config.chunk_samples
        end = min(self._read_pos + chunk_size, self._total_samples)
        samples = self._data[:, self._read_pos:end]
        n_samples = samples.shape[1]
        t0 = self._read_pos / self._sample_rate
        timestamps = t0 + np.arange(n_samples) / self._sample_rate
        self._read_pos = end

        return DataChunk(
            samples=samples, timestamps=timestamps,
            channel_ids=self._channel_ids, sample_rate=self._sample_rate,
        )

    def close(self) -> None:
        self._data = None
        self._read_pos = 0

    @property
    def progress(self) -> float:
        if self._total_samples == 0:
            return 0.0
        return self._read_pos / self._total_samples
