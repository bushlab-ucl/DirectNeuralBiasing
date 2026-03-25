"""Data source for Blackrock NPlay simulator.

Wraps the pycbsdk Session to receive packets from NPlay, converting
the callback-driven API into the pull-based DataSource interface via
a thread-safe queue.
"""

from __future__ import annotations

import logging
import queue
import time

import numpy as np

from dnb.core.types import DataChunk, PipelineConfig
from dnb.sources.base import DataSource

logger = logging.getLogger(__name__)

# Cerebus packet constants
_CONTINUOUS_PACKET_TYPE = 6
_HEADER_INT16_COUNT = 6
_SAMPLES_PER_PACKET = 6


class NPlaySource(DataSource):
    """Reads continuous data from a Blackrock NPlay instance via pycbsdk.

    Packets arrive via a callback on pycbsdk's handler thread and are
    queued for consumption by read_chunk(). Chunks are assembled from
    multiple packets until the configured chunk duration is reached.

    Args:
        protocol: Protocol string for pycbsdk Session (default "NPLAY").
        startup_delay: Seconds to wait after session connect for device init.
        queue_maxsize: Maximum queued packets before dropping.
    """

    def __init__(
        self,
        protocol: str = "NPLAY",
        startup_delay: float = 2.0,
        queue_maxsize: int = 50_000,
    ) -> None:
        self._protocol = protocol
        self._startup_delay = startup_delay
        self._queue: queue.Queue[tuple[int, np.ndarray]] = queue.Queue(
            maxsize=queue_maxsize
        )
        self._session = None
        self._config: PipelineConfig | None = None
        self._connected = False

    def connect(self, config: PipelineConfig) -> None:
        from pycbsdk import Session

        self._config = config
        self._session = Session(self._protocol)
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
                pass  # Drop malformed or overflow packets

        self._connected = True
        logger.info("NPlaySource connected (protocol=%s)", self._protocol)

    def read_chunk(self) -> DataChunk | None:
        """Assemble packets into a chunk of configured duration.

        Blocks until enough packets arrive to fill one chunk, or returns
        a partial chunk on timeout.
        """
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

        # Convert packet timestamps to seconds
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
        self._connected = False
        logger.info("NPlaySource closed")
