"""File data source — reads .npz files chunk by chunk, single channel."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from dnb.core.types import DataChunk, PipelineConfig
from dnb.sources.base import DataSource

logger = logging.getLogger(__name__)


class FileSource(DataSource):
    """Reads continuous data from a saved .npz file.

    Expected keys: 'continuous' (any shape — extracts 1D), 'sample_rate'.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._data: np.ndarray | None = None
        self._sample_rate: float = 0.0
        self._channel_id: int = 0
        self._read_pos: int = 0
        self._total_samples: int = 0
        self._chunk_samples: int = 0
        self._resolved_config: PipelineConfig | None = None

    @property
    def resolved_config(self) -> PipelineConfig | None:
        return self._resolved_config

    def connect(self, config: PipelineConfig) -> None:
        if not self._path.exists():
            raise FileNotFoundError(f"Data file not found: {self._path}")

        npz = np.load(str(self._path), allow_pickle=False)
        raw = npz["continuous"].astype(np.float64)
        self._sample_rate = float(npz["sample_rate"])
        self._channel_id = config.channel_id

        # Extract single channel → 1D
        if raw.ndim == 2:
            ch_idx = min(self._channel_id, raw.shape[0] - 1)
            self._data = raw[ch_idx]
        elif raw.ndim == 1:
            self._data = raw
        else:
            self._data = raw.ravel()

        self._total_samples = self._data.shape[0]
        self._read_pos = 0
        self._chunk_samples = int(config.chunk_duration * self._sample_rate)

        self._resolved_config = PipelineConfig(
            sample_rate=self._sample_rate,
            channel_id=self._channel_id,
            buffer_duration=config.buffer_duration,
            chunk_duration=config.chunk_duration,
        )
        logger.info(
            "FileSource: %s (ch=%d, %.1fs @ %.0f Hz, chunk=%d samples)",
            self._path.name, self._channel_id,
            self._total_samples / self._sample_rate,
            self._sample_rate, self._chunk_samples,
        )

    def read_chunk(self) -> DataChunk | None:
        if self._data is None:
            raise RuntimeError("Source not connected.")
        if self._read_pos >= self._total_samples:
            return None

        end = min(self._read_pos + self._chunk_samples, self._total_samples)
        samples = self._data[self._read_pos:end]
        n_samples = samples.shape[0]
        t0 = self._read_pos / self._sample_rate
        timestamps = t0 + np.arange(n_samples) / self._sample_rate
        self._read_pos = end

        return DataChunk(
            samples=samples,
            timestamps=timestamps,
            channel_id=self._channel_id,
            sample_rate=self._sample_rate,
        )

    def close(self) -> None:
        self._data = None
        self._read_pos = 0

    @property
    def progress(self) -> float:
        if self._total_samples == 0:
            return 0.0
        return self._read_pos / self._total_samples