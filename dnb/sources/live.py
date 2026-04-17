"""Live data sources for Blackrock hardware — single channel.

Matches the C++ architecture:
    1. Connect to device
    2. Set up trial config for continuous data
    3. Poll cbSdkGetTrialData in a loop
    4. Extract the one channel we care about
    5. Convert INT16 → float64

Supports two pycbsdk versions:
  - OLD standalone pycbsdk (<=0.4.1): Session + polling API
  - NEW CereLink-bundled pycbsdk (>=9.x): cbsdk procedural API

The old API previously used a callback approach that registered
on_packet after session start — this was unreliable (packets could
arrive before callback registration, or the packet type constant
was wrong). Now both APIs use a polling approach matching the C++.

Install: pip install pycbsdk
"""

from __future__ import annotations

import logging
import time

import numpy as np

from dnb.core.types import DataChunk, PipelineConfig
from dnb.sources.base import DataSource

logger = logging.getLogger(__name__)


def _detect_pycbsdk_version() -> str:
    """Detect which pycbsdk API is available."""
    try:
        from pycbsdk import cbsdk
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
# Old API (standalone pycbsdk <= 0.4.1) — polling approach
# ---------------------------------------------------------------------------

class _OldBlackrockSource(DataSource):
    """Old pycbsdk Session-based source — polling, single channel.

    Uses get_continuous_data() polling instead of on_packet callbacks.
    This matches the C++ pattern and avoids the callback registration
    timing issues.
    """

    def __init__(self, startup_delay: float = 2.0) -> None:
        self._startup_delay = startup_delay
        self._session = None
        self._config: PipelineConfig | None = None
        self._channel_id: int = 0

    def _create_session(self):
        raise NotImplementedError

    def connect(self, config: PipelineConfig) -> None:
        self._config = config
        self._channel_id = config.channel_id
        self._session = self._create_session()
        self._session.__enter__()
        logger.info("Old pycbsdk session opened, waiting %.1fs for device...", self._startup_delay)
        time.sleep(self._startup_delay)
        logger.info("Old pycbsdk ready, channel=%d", self._channel_id)

    def read_chunk(self) -> DataChunk | None:
        if not self._config or not self._session:
            raise RuntimeError("Source not connected.")

        try:
            # get_continuous_data returns dict: {channel_id: (timestamps, samples)}
            # or similar depending on pycbsdk version
            data = self._session.get_continuous_data()

            if data is None or not data:
                return None

            # Find our channel
            if self._channel_id in data:
                channel_data = data[self._channel_id]
            elif isinstance(data, dict):
                # Try numeric channel lookup
                matching = [v for k, v in data.items()
                            if (isinstance(k, int) and k == self._channel_id)]
                if not matching:
                    return None
                channel_data = matching[0]
            else:
                return None

            # channel_data might be (timestamps, samples) or just samples
            if isinstance(channel_data, tuple) and len(channel_data) == 2:
                _, raw_samples = channel_data
            else:
                raw_samples = channel_data

            if raw_samples is None or len(raw_samples) == 0:
                return None

            # Convert to float64 (Blackrock INT16 → µV: multiply by 0.25)
            samples = np.asarray(raw_samples, dtype=np.float64)
            if samples.dtype == np.int16 or np.issubdtype(samples.dtype, np.integer):
                samples = samples.astype(np.float64) * 0.25

            # 1D
            samples = samples.ravel()
            n_samples = samples.shape[0]

            # Generate timestamps
            # Note: for precise timing, we'd use device timestamps.
            # This uses sample count as a proxy.
            t0 = 0.0  # Will be overridden by pipeline's ring buffer tracking
            timestamps = t0 + np.arange(n_samples) / self._config.sample_rate

            return DataChunk(
                samples=samples,
                timestamps=timestamps,
                channel_id=self._channel_id,
                sample_rate=self._config.sample_rate,
            )

        except AttributeError:
            # get_continuous_data not available — fall back to callback approach
            logger.warning(
                "get_continuous_data() not available in this pycbsdk version. "
                "Falling back to packet-based reading. Consider upgrading pycbsdk."
            )
            return self._read_chunk_callback_fallback()

        except Exception:
            logger.exception("Error reading continuous data")
            return None

    def _read_chunk_callback_fallback(self) -> DataChunk | None:
        """Fallback for old pycbsdk versions without get_continuous_data.

        Uses the trial-based API if available, similar to the C++ approach.
        """
        try:
            # Try trial-based approach
            trial = self._session.get_trial_data()
            if trial is None:
                return None

            # Extract channel data from trial
            # Structure varies by pycbsdk version
            if hasattr(trial, 'continuous') and self._channel_id in trial.continuous:
                raw_samples = trial.continuous[self._channel_id]
            else:
                return None

            if raw_samples is None or len(raw_samples) == 0:
                return None

            samples = np.asarray(raw_samples, dtype=np.float64).ravel()
            if np.issubdtype(np.asarray(raw_samples).dtype, np.integer):
                samples *= 0.25

            n_samples = samples.shape[0]
            timestamps = np.arange(n_samples) / self._config.sample_rate

            return DataChunk(
                samples=samples,
                timestamps=timestamps,
                channel_id=self._channel_id,
                sample_rate=self._config.sample_rate,
            )

        except Exception:
            logger.exception("Fallback read failed")
            return None

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.__exit__(None, None, None)
            except Exception:
                logger.exception("Error closing session")
            self._session = None


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
# New API (CereLink-bundled pycbsdk >= 9.x) — polling approach
# ---------------------------------------------------------------------------

class _NewBlackrockSource(DataSource):
    """New CereLink CFFI-based pycbsdk — polling, single channel.

    Mirrors the C++ main loop:
        cbSdkSetTrialConfig(...)
        while running:
            cbSdkGetTrialData(...)
            extract channel → process
    """

    def __init__(self, startup_delay: float = 2.0) -> None:
        self._startup_delay = startup_delay
        self._nsp = None
        self._config: PipelineConfig | None = None
        self._channel_id: int = 0

    def _create_params(self):
        raise NotImplementedError

    def connect(self, config: PipelineConfig) -> None:
        from pycbsdk import cbsdk

        self._config = config
        self._channel_id = config.channel_id

        params = self._create_params()
        self._nsp = cbsdk.get_device(params)
        cbsdk.connect(self._nsp)
        logger.info("New pycbsdk connected, waiting %.1fs...", self._startup_delay)
        time.sleep(self._startup_delay)

        # Set up trial config for continuous data (mirrors C++ cbSdkSetTrialConfig)
        try:
            cbsdk.set_trial_config(self._nsp, reset=True, buffer_parameter={
                "continuous_length": config.chunk_samples,
            })
            logger.info("Trial config set (continuous_length=%d)", config.chunk_samples)
        except (AttributeError, TypeError):
            # API might differ — try alternative
            try:
                cbsdk.trial_config(self._nsp, reset=1, begchan=0,
                                   begmask=0, begval=0,
                                   endchan=0, endmask=0, endval=0)
                logger.info("Trial config set (legacy API)")
            except Exception:
                logger.warning("Could not set trial config — data may not stream")

        logger.info("New pycbsdk ready, channel=%d", self._channel_id)

    def read_chunk(self) -> DataChunk | None:
        if not self._config or not self._nsp:
            raise RuntimeError("Source not connected.")

        from pycbsdk import cbsdk

        try:
            # Get trial data (mirrors C++ cbSdkGetTrialData)
            trial = cbsdk.get_trial_data(self._nsp)

            if trial is None:
                return None

            # trial is typically a dict or object with continuous data per channel
            # Structure: {channel_id: samples_array} or similar
            raw_samples = None

            if isinstance(trial, dict):
                # Direct dict lookup
                if self._channel_id in trial:
                    raw_samples = trial[self._channel_id]
                else:
                    # Try looking through available channels
                    for ch_id, ch_data in trial.items():
                        if ch_id == self._channel_id:
                            raw_samples = ch_data
                            break
            elif hasattr(trial, 'continuous'):
                # Object with .continuous attribute
                cont = trial.continuous
                if isinstance(cont, dict) and self._channel_id in cont:
                    raw_samples = cont[self._channel_id]
                elif isinstance(cont, (list, np.ndarray)) and len(cont) > 0:
                    # Array indexed by channel
                    idx = min(self._channel_id, len(cont) - 1)
                    raw_samples = cont[idx]

            if raw_samples is None or len(raw_samples) == 0:
                return None

            # Convert INT16 → float64 µV (0.25 conversion factor, matching C++)
            samples = np.asarray(raw_samples, dtype=np.float64).ravel()
            if np.issubdtype(np.asarray(raw_samples).dtype, np.integer):
                samples *= 0.25

            n_samples = samples.shape[0]
            timestamps = np.arange(n_samples) / self._config.sample_rate

            return DataChunk(
                samples=samples,
                timestamps=timestamps,
                channel_id=self._channel_id,
                sample_rate=self._config.sample_rate,
            )

        except Exception:
            logger.exception("Error reading trial data")
            return None

    def close(self) -> None:
        if self._nsp is not None:
            try:
                from pycbsdk import cbsdk
                cbsdk.disconnect(self._nsp)
            except Exception:
                logger.exception("Error during disconnect")
            self._nsp = None


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
# Public classes — auto-detect API version
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
    """Reads from Blackrock NPlay simulator — single channel.

    Auto-detects old vs new pycbsdk and delegates accordingly.
    Channel selection via PipelineConfig.channel_id.
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
    """Reads from live Blackrock Cerebus NSP — single channel.

    Auto-detects old vs new pycbsdk and delegates accordingly.
    Channel selection via PipelineConfig.channel_id.
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