"""Event detection module operating on wavelet-decomposed signals.

Detects neural events (ripples, sharp waves, spindles, etc.) by
analysing the amplitude and phase output from the WaveletConvolution
module. Supports threshold-based detection on band-specific amplitude
envelopes.
"""

from __future__ import annotations

import logging

import numpy as np
from numpy.typing import NDArray
from scipy.ndimage import label as ndimage_label

from dnb.core.types import Event, EventType, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)

# Number of chunks used to build up a stable baseline before events
# are emitted.  During warmup the running mean/var are updated but
# no threshold crossings are reported.
_DEFAULT_WARMUP_CHUNKS = 5


class EventDetector(Module):
    """Detect events from wavelet amplitude envelopes.

    Looks for threshold crossings in the amplitude of specified frequency
    bands. Events are emitted when the amplitude exceeds threshold_std
    standard deviations above the running mean.

    A brief warmup period (``warmup_chunks`` chunks) is enforced at the
    start of each run so that the running statistics converge before
    detection begins.

    Args:
        event_type: Type of event to emit.
        freq_range: (low, high) Hz band to monitor. The detector will
            average amplitude across all wavelet frequencies in this range.
        threshold_std: Number of standard deviations above mean for detection.
        min_duration: Minimum event duration in seconds.
        channels: Which channels to monitor. None = all.
        cooldown: Minimum seconds between events on the same channel.
        warmup_chunks: Number of initial chunks used only for baseline
            estimation (no events emitted).
    """

    def __init__(
        self,
        event_type: EventType = EventType.THRESHOLD_CROSSING,
        freq_range: tuple[float, float] = (80.0, 250.0),
        threshold_std: float = 3.0,
        min_duration: float = 0.02,
        channels: list[int] | None = None,
        cooldown: float = 0.1,
        warmup_chunks: int = _DEFAULT_WARMUP_CHUNKS,
    ) -> None:
        self._event_type = event_type
        self._freq_range = freq_range
        self._threshold_std = threshold_std
        self._min_duration = min_duration
        self._channels = channels
        self._cooldown = cooldown
        self._warmup_chunks = warmup_chunks

        # Running statistics (exponential moving average)
        self._running_mean: NDArray[np.float64] | None = None
        self._running_var: NDArray[np.float64] | None = None
        self._alpha = 0.01  # EMA decay rate
        self._last_event_time: dict[int, float] = {}
        self._config: PipelineConfig | None = None
        self._chunks_seen: int = 0

    def configure(self, config: PipelineConfig) -> None:
        self._config = config

    def process(self, result: ProcessResult) -> ProcessResult:
        if result.wavelet is None:
            logger.warning("EventDetector received no wavelet data — skipping.")
            return result

        wavelet = result.wavelet
        chunk = result.chunk

        # Find frequency indices within the target range
        freq_mask = (wavelet.frequencies >= self._freq_range[0]) & (
            wavelet.frequencies <= self._freq_range[1]
        )
        if not np.any(freq_mask):
            return result

        # Average amplitude across the target frequency band
        # Shape: (n_channels_wavelet, n_samples)
        band_amplitude = np.mean(wavelet.amplitude[:, freq_mask, :], axis=1)

        # Channel selection — the wavelet may have already filtered channels
        # (fewer rows than the chunk). We need to figure out which channel
        # IDs correspond to the wavelet's rows.
        n_wavelet_ch = wavelet.analytic.shape[0]
        if n_wavelet_ch == chunk.n_channels:
            # Wavelet has all channels — apply our own filter if set
            if self._channels is not None:
                ch_mask = np.isin(chunk.channel_ids, self._channels)
                band_amplitude = band_amplitude[ch_mask]
                ch_ids = chunk.channel_ids[ch_mask]
            else:
                ch_ids = chunk.channel_ids
        else:
            # Wavelet already selected a subset — use its rows as-is.
            # Try to recover channel IDs from the chunk if possible.
            if self._channels is not None:
                ch_mask = np.isin(chunk.channel_ids, self._channels)
                ch_ids = chunk.channel_ids[ch_mask][:n_wavelet_ch]
            else:
                ch_ids = np.arange(n_wavelet_ch, dtype=np.int32)

        n_ch = band_amplitude.shape[0]

        # Update running statistics
        chunk_mean = np.mean(band_amplitude, axis=1)  # (n_ch,)
        chunk_var = np.var(band_amplitude, axis=1)

        if self._running_mean is None or self._running_mean.shape[0] != n_ch:
            self._running_mean = chunk_mean.copy()
            self._running_var = chunk_var.copy()
        else:
            self._running_mean = (
                self._alpha * chunk_mean + (1 - self._alpha) * self._running_mean
            )
            self._running_var = (
                self._alpha * chunk_var + (1 - self._alpha) * self._running_var
            )

        self._chunks_seen += 1

        # During warmup, update stats only — do not detect events.
        if self._chunks_seen <= self._warmup_chunks:
            return result

        # Threshold detection
        running_std = np.sqrt(self._running_var)
        threshold = self._running_mean + self._threshold_std * running_std

        min_samples = int(self._min_duration * chunk.sample_rate)
        events: list[Event] = []

        for ci in range(n_ch):
            ch_id = int(ch_ids[ci])
            above = band_amplitude[ci] > threshold[ci]

            # Use scipy.ndimage.label for robust contiguous-region detection.
            # This correctly handles all edge cases (signal entirely above
            # threshold, single-sample dips, etc.).
            labelled, n_regions = ndimage_label(above)

            for region_id in range(1, n_regions + 1):
                region_indices = np.where(labelled == region_id)[0]
                start = region_indices[0]
                stop = region_indices[-1] + 1
                duration_samp = stop - start

                if duration_samp < min_samples:
                    continue

                t = chunk.timestamps[start]

                # Cooldown check
                last_t = self._last_event_time.get(ch_id, -np.inf)
                if t - last_t < self._cooldown:
                    continue

                duration = duration_samp / chunk.sample_rate
                peak_amp = float(np.max(band_amplitude[ci, start:stop]))

                events.append(
                    Event(
                        event_type=self._event_type,
                        timestamp=t,
                        channel_id=ch_id,
                        duration=duration,
                        metadata={
                            "peak_amplitude": peak_amp,
                            "threshold": float(threshold[ci]),
                            "freq_range": self._freq_range,
                        },
                    )
                )
                self._last_event_time[ch_id] = t

        result.events.extend(events)
        return result

    def reset(self) -> None:
        self._running_mean = None
        self._running_var = None
        self._last_event_time.clear()
        self._chunks_seen = 0