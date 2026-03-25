"""Data source for live Blackrock Cerebus NSP hardware.

Identical architecture to NPlaySource but connects to real hardware.
Uses protocol="" (default) or a custom IP for direct NSP connection.
"""

from __future__ import annotations

import logging
import queue
import time

import numpy as np

from dnb.core.types import DataChunk, PipelineConfig
from dnb.sources.base import DataSource

logger = logging.getLogger(__name__)

_CONTINUOUS_PACKET_TYPE = 6
_HEADER_INT16_COUNT = 6
_SAMPLES_PER_PACKET = 6


class CerebusSource(DataSource):
    """Reads continuous data from a live Blackrock Cerebus NSP.

    Args:
        inst_addr: IP address of the NSP (default: auto-discover).
        client_addr: IP address of the local interface to bind.
        startup_delay: Seconds to wait after session connect.
        queue_maxsize: Maximum queued packets before dropping.
    """

    def __init__(
        self,
        inst_addr: str = "",
        client_addr: str = "0.0.0.0",
        startup_delay: float = 2.0,
        queue_maxsize: int = 50_000,
    ) -> None:
        self._inst_addr = inst_addr
        self._client_addr = client_addr
        self._startup_delay = startup_delay
        self._queue: queue.Queue[tuple[int, np.ndarray]] = queue.Queue(
            maxsize=queue_maxsize
        )
        self._session = None
        self._config: PipelineConfig | None = None

    def connect(self, config: PipelineConfig) -> None:
        from pycbsdk import Session

        self._config = config

        # Live hardware uses default protocol with explicit addresses
        self._session = Session(
            inst_addr=self._inst_addr,
            client_addr=self._client_addr,
        )
        self._session.__enter__()
        time.sleep(self._startup_delay)

        @self._session.on_packet()
        def _on_packet(header, data):
            if header.type != _CONTINUOUS_PACKET_TYPE:
                return
            try:
                raw = np.frombuffer(bytes(data), dtype=np.int16).copy()
                payload = raw[_HEADER_INT16_COUNT:]
                samples = payload.reshape(config.n_channels, _SAMPLES_PER_PACKET)
                self._queue.put_nowait((header.time, samples))
            except (ValueError, queue.Full):
                pass

        logger.info(
            "CerebusSource connected (inst=%s, client=%s)",
            self._inst_addr,
            self._client_addr,
        )

    def read_chunk(self) -> DataChunk | None:
        if not self._config:
            raise RuntimeError("Source not connected. Call connect() first.")

        target_samples = self._config.chunk_samples
        packets_needed = max(1, target_samples // _SAMPLES_PER_PACKET)

        collected_times: list[int] = []
        collected_samples: list[np.ndarray] = []

        for _ in range(packets_needed):
            try:
                t, s = self._queue.get(timeout=1.0)
                collected_times.append(t)
                collected_samples.append(s)
            except queue.Empty:
                break

        if not collected_samples:
            return None

        samples = np.concatenate(collected_samples, axis=1).astype(np.float64)
        n_samples = samples.shape[1]
        t0 = collected_times[0] / self._config.sample_rate
        timestamps = t0 + np.arange(n_samples) / self._config.sample_rate

        return DataChunk(
            samples=samples,
            timestamps=timestamps,
            channel_ids=self._config.channel_ids,
            sample_rate=self._config.sample_rate,
        )

    def close(self) -> None:
        if self._session is not None:
            self._session.__exit__(None, None, None)
            self._session = None
        logger.info("CerebusSource closed")
