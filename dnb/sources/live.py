"""Live data sources for Blackrock hardware.

Supports two pycbsdk versions:
  - OLD standalone pycbsdk (<=0.4.1): Session context-manager API
  - NEW CereLink-bundled pycbsdk (>=9.x): cbsdk procedural API

Install: pip install pycbsdk
    (As of March 2026, this installs the new CereLink CFFI version.
     For the old version: pip install pycbsdk==0.4.1)

The module auto-detects which API is available and adapts accordingly.
"""

from __future__ import annotations

import logging
import queue
import time

import numpy as np

from dnb.core.types import DataChunk, PipelineConfig
from dnb.sources.base import DataSource

logger = logging.getLogger(__name__)

# Packet constants for the old Session-based API
_CONTINUOUS_PACKET_TYPE = 6
_HEADER_INT16_COUNT = 6
_SAMPLES_PER_PACKET = 6


def _detect_pycbsdk_version() -> str:
    """Detect which pycbsdk API is available.

    Returns:
        'new' for CereLink-bundled CFFI version
        'old' for standalone pure-Python version
        'none' if not installed
    """
    try:
        from pycbsdk import cbsdk
        # New API has create_params
        if hasattr(cbsdk, 'create_params'):
            return 'new'
    except ImportError:
        pass

    try:
        from pycbsdk import Session  # noqa: F401
        return 'old'
    except ImportError:
        pass

    return 'none'


# ---------------------------------------------------------------------------
# Old API (standalone pycbsdk <= 0.4.1)
# ---------------------------------------------------------------------------

class _OldBlackrockSource(DataSource):
    """Base for old pycbsdk Session-based sources."""

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


class _OldNPlaySource(_OldBlackrockSource):
    def __init__(self, protocol: str = "NPLAY", **kwargs) -> None:
        super().__init__(**kwargs)
        self._protocol = protocol

    def _create_session(self):
        from pycbsdk import Session
        return Session(self._protocol)


class _OldCerebusSource(_OldBlackrockSource):
    def __init__(self, inst_addr: str = "", client_addr: str = "0.0.0.0", **kwargs) -> None:
        super().__init__(**kwargs)
        self._inst_addr = inst_addr
        self._client_addr = client_addr

    def _create_session(self):
        from pycbsdk import Session
        return Session(inst_addr=self._inst_addr, client_addr=self._client_addr)


# ---------------------------------------------------------------------------
# New API (CereLink-bundled pycbsdk >= 9.x)
# ---------------------------------------------------------------------------

class _NewBlackrockSource(DataSource):
    """Base for new CereLink CFFI-based pycbsdk.

    Uses cbsdk.create_params() / get_device() / connect() API with
    callback-based continuous data retrieval.
    """

    def __init__(self, queue_maxsize: int = 500_000, startup_delay: float = 2.0) -> None:
        self._startup_delay = startup_delay
        self._queue: queue.Queue = queue.Queue(maxsize=queue_maxsize)
        self._nsp = None
        self._config: PipelineConfig | None = None
        self._dropped_packets = 0
        self._channel_index: int = 0  # which channel to extract

    def _create_params(self):
        raise NotImplementedError

    def connect(self, config: PipelineConfig) -> None:
        from pycbsdk import cbsdk

        self._config = config
        self._dropped_packets = 0

        params = self._create_params()
        self._nsp = cbsdk.get_device(params)
        cbsdk.connect(self._nsp)
        time.sleep(self._startup_delay)

        # Register continuous data callback
        def _on_continuous(channel_id, data):
            """Called per-channel per-packet with continuous samples."""
            try:
                samples = np.array(data, dtype=np.float64).reshape(1, -1)
                timestamp = time.perf_counter()  # device time comes via sync
                self._queue.put_nowait((timestamp, samples))
            except (ValueError, queue.Full):
                self._dropped_packets += 1

        # Register for the target channel(s)
        # The new API uses register_group_callback or register_event_callback
        # depending on version. Try the most common approach.
        try:
            cbsdk.register_group_callback(self._nsp, 6, _on_continuous)
            logger.info("Registered group callback (group 6 = 30kHz continuous)")
        except (AttributeError, TypeError):
            # Fallback: try per-channel registration
            try:
                for ch_id in config.channel_ids:
                    cbsdk.register_event_callback(
                        self._nsp, "continuous", _on_continuous,
                    )
                logger.info("Registered event callbacks for continuous data")
            except Exception:
                logger.warning(
                    "Could not register continuous data callback. "
                    "You may need to adjust the callback registration for "
                    "your pycbsdk version."
                )

        logger.info("Connected to device (new pycbsdk API)")

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
        # Use first packet time as reference
        t0 = times[0]
        timestamps = t0 + np.arange(samples.shape[1]) / self._config.sample_rate

        return DataChunk(
            samples=samples, timestamps=timestamps,
            channel_ids=self._config.channel_ids, sample_rate=self._config.sample_rate,
        )

    def close(self) -> None:
        if self._nsp is not None:
            try:
                from pycbsdk import cbsdk
                cbsdk.disconnect(self._nsp)
            except Exception:
                logger.exception("Error during disconnect")
            self._nsp = None
        if self._dropped_packets > 0:
            logger.warning("Closed — %d packets dropped", self._dropped_packets)


class _NewNPlaySource(_NewBlackrockSource):
    def __init__(self, protocol: str = "NPLAY", **kwargs) -> None:
        super().__init__(**kwargs)
        self._protocol = protocol

    def _create_params(self):
        from pycbsdk import cbsdk
        return cbsdk.create_params(protocol=self._protocol)


class _NewCerebusSource(_NewBlackrockSource):
    def __init__(self, inst_addr: str = "", client_addr: str = "0.0.0.0", **kwargs) -> None:
        super().__init__(**kwargs)
        self._inst_addr = inst_addr
        self._client_addr = client_addr

    def _create_params(self):
        from pycbsdk import cbsdk
        kwargs = {}
        if self._inst_addr:
            kwargs["inst_addr"] = self._inst_addr
        if self._client_addr:
            kwargs["client_addr"] = self._client_addr
        return cbsdk.create_params(**kwargs)


# ---------------------------------------------------------------------------
# Public factory functions — auto-detect API version
# ---------------------------------------------------------------------------

_API_VERSION: str | None = None


def _get_api_version() -> str:
    global _API_VERSION
    if _API_VERSION is None:
        _API_VERSION = _detect_pycbsdk_version()
        if _API_VERSION == 'none':
            raise ImportError(
                "pycbsdk not installed. Install with: pip install pycbsdk\n"
                "  (For the old version: pip install pycbsdk==0.4.1)"
            )
        logger.info("Detected pycbsdk API: %s", _API_VERSION)
    return _API_VERSION


class NPlaySource(DataSource):
    """Reads from Blackrock NPlay simulator.

    Auto-detects old vs new pycbsdk and delegates accordingly.
    """

    def __init__(self, protocol: str = "NPLAY", **kwargs) -> None:
        api = _get_api_version()
        if api == 'old':
            self._impl = _OldNPlaySource(protocol=protocol, **kwargs)
        else:
            self._impl = _NewNPlaySource(protocol=protocol, **kwargs)

    def connect(self, config: PipelineConfig) -> None:
        self._impl.connect(config)

    def read_chunk(self) -> DataChunk | None:
        return self._impl.read_chunk()

    def close(self) -> None:
        self._impl.close()


class CerebusSource(DataSource):
    """Reads from live Blackrock Cerebus NSP hardware.

    Auto-detects old vs new pycbsdk and delegates accordingly.
    """

    def __init__(self, inst_addr: str = "", client_addr: str = "0.0.0.0", **kwargs) -> None:
        api = _get_api_version()
        if api == 'old':
            self._impl = _OldCerebusSource(inst_addr=inst_addr, client_addr=client_addr, **kwargs)
        else:
            self._impl = _NewCerebusSource(inst_addr=inst_addr, client_addr=client_addr, **kwargs)

    def connect(self, config: PipelineConfig) -> None:
        self._impl.connect(config)

    def read_chunk(self) -> DataChunk | None:
        return self._impl.read_chunk()

    def close(self) -> None:
        self._impl.close()