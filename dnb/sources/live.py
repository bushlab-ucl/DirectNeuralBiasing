"""Live data sources for Blackrock hardware.

These require pycbsdk: pip install direct-neural-biasing[live]
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


class _BlackrockSource(DataSource):
    """Base class for pycbsdk-based sources (NPlay and Cerebus)."""

    def __init__(self, queue_maxsize: int = 500_000, startup_delay: float = 2.0) -> None:
        self._startup_delay = startup_delay
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._session = None
        self._config: PipelineConfig | None = None
        self._dropped_packets = 0

    def _create_session(self):
        raise NotImplementedError

    def connect(self, config: PipelineConfig) -> None:
        self._config = config
        self._dropped_packets = 0
        self._session = self._create_session()
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
                self._dropped_packets += 1

    def read_chunk(self) -> DataChunk | None:
        if not self._config:
            raise RuntimeError("Source not connected.")

        target = self._config.chunk_samples
        times, chunks = [], []
        n = 0

        while n < target:
            try:
                t, s = self._queue.get(timeout=0.05)
                times.append(t)
                chunks.append(s)
                n += s.shape[1]
            except queue.Empty:
                if not chunks:
                    return None
                break

        samples = np.concatenate(chunks, axis=1).astype(np.float64)
        t0 = times[0] / self._config.sample_rate
        timestamps = t0 + np.arange(samples.shape[1]) / self._config.sample_rate

        return DataChunk(
            samples=samples, timestamps=timestamps,
            channel_ids=self._config.channel_ids, sample_rate=self._config.sample_rate,
        )

    def close(self) -> None:
        if self._session is not None:
            self._session.__exit__(None, None, None)
            self._session = None
        if self._dropped_packets > 0:
            logger.warning("Closed — %d packets dropped", self._dropped_packets)


class NPlaySource(_BlackrockSource):
    """Reads from Blackrock NPlay simulator via pycbsdk."""

    def __init__(self, protocol: str = "NPLAY", **kwargs) -> None:
        super().__init__(**kwargs)
        self._protocol = protocol

    def _create_session(self):
        from pycbsdk import Session
        return Session(self._protocol)


class CerebusSource(_BlackrockSource):
    """Reads from live Blackrock Cerebus NSP hardware."""

    def __init__(self, inst_addr: str = "", client_addr: str = "0.0.0.0", **kwargs) -> None:
        super().__init__(**kwargs)
        self._inst_addr = inst_addr
        self._client_addr = client_addr

    def _create_session(self):
        from pycbsdk import Session
        return Session(inst_addr=self._inst_addr, client_addr=self._client_addr)
