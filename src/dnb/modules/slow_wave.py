"""Slow wave detection and stimulation trigger module.

Uses the wavelet decomposition output to detect slow oscillations
(0.5–2 Hz) and trigger stimulation at a target phase. Adapted from
the TWave phase-tracking algorithm (Hedemann et al.) to work on
chunk-based wavelet output.

Detection criteria (all must be met for STIM1):
    1. Phase at target (within tolerance)
    2. Amplitude above minimum threshold
    3. Amplitude below maximum threshold (artifact rejection)
    4. High-frequency / low-frequency power ratio below limit (IED rejection)
    5. Backoff period elapsed since last stimulation
    6. Warmup period elapsed since pipeline start

After STIM1, a STIM2 (paired pulse) is triggered after a configurable
inter-stimulus delay when phase next hits target.
"""

from __future__ import annotations

import logging
from math import pi

import numpy as np
from numpy.typing import NDArray

from dnb.core.types import Event, EventType, PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class SlowWaveDetector(Module):
    """Wavelet-based slow wave detector with phase-targeted stimulation.

    Sits after WaveletConvolution in the pipeline. Reads instantaneous
    phase and amplitude from the wavelet output in the slow oscillation
    band, applies inhibition criteria, and emits STIM1/STIM2 events
    when conditions are met.

    When ``event_window_s`` > 0, the raw signal around each detected
    event is extracted from the ring buffer and stored in the event's
    metadata under the key ``"raw_window"``.  The window spans
    ±event_window_s seconds centred on the detection timestamp.

    Args:
        target_phase: Target phase in radians (0 = negative peak).
        phase_tolerance: Half-width of the phase acceptance window in radians.
        freq_range: (low, high) Hz for the slow oscillation band.
        hf_freq_range: (low, high) Hz for the high-frequency ratio check.
        amp_min: Minimum slow-wave amplitude (µV) to allow stimulation.
        amp_max: Maximum slow-wave amplitude (µV) — above this, inhibit
            (artifact / IED rejection).
        hf_ratio_max: Maximum HF/LF power ratio — above this, inhibit
            (IED rejection).
        backoff_s: Minimum seconds after STIM1 before next STIM1.
        stim2_delay_s: Delay in seconds after STIM1 before STIM2 window opens.
        stim2_window_s: Duration of the STIM2 acceptance window.
        warmup_chunks: Number of chunks to skip at start for baseline.
        channels: Which channels to monitor. None = all.
        amp_smoothing: Number of chunks to average amplitude over.
        event_window_s: Half-width (seconds) of raw signal to capture around
            each event.  Set to 0 to disable window capture.  The window
            is read from the ring buffer at the *current* sample rate
            (post-downsampling if a Downsampler is present).
    """

    def __init__(
        self,
        target_phase: float = 0.0,
        phase_tolerance: float = 0.3,
        freq_range: tuple[float, float] = (0.5, 2.0),
        hf_freq_range: tuple[float, float] = (10.0, 40.0),
        amp_min: float = 50.0,
        amp_max: float = 5000.0,
        hf_ratio_max: float = 0.5,
        backoff_s: float = 5.0,
        stim2_delay_s: float = 0.6,
        stim2_window_s: float = 5.0,
        warmup_chunks: int = 10,
        channels: list[int] | None = None,
        amp_smoothing: int = 5,
        event_window_s: float = 1.0,
    ) -> None:
        self._target_phase = target_phase % (2 * pi)
        self._phase_tolerance = phase_tolerance
        self._freq_range = freq_range
        self._hf_freq_range = hf_freq_range
        self._amp_min = amp_min
        self._amp_max = amp_max
        self._hf_ratio_max = hf_ratio_max
        self._backoff_s = backoff_s
        self._stim2_delay_s = stim2_delay_s
        self._stim2_window_s = stim2_window_s
        self._warmup_chunks = warmup_chunks
        self._channels = channels
        self._amp_smoothing = amp_smoothing
        self._event_window_s = event_window_s

        # State
        self._config: PipelineConfig | None = None
        self._chunks_seen: int = 0
        self._last_stim1_time: dict[int, float] = {}  # per channel
        self._awaiting_stim2: dict[int, float] = {}  # ch_id -> stim1 time
        self._amp_history: dict[int, list[float]] = {}  # ch_id -> recent amplitudes

    def configure(self, config: PipelineConfig) -> None:
        self._config = config
        logger.info(
            "SlowWaveDetector configured: target_phase=%.2f rad, "
            "freq_range=(%.1f, %.1f) Hz, amp=(%.0f, %.0f), "
            "backoff=%.1fs, stim2_delay=%.1fs, event_window=±%.1fs",
            self._target_phase,
            self._freq_range[0], self._freq_range[1],
            self._amp_min, self._amp_max,
            self._backoff_s, self._stim2_delay_s,
            self._event_window_s,
        )

    def _extract_event_window(
        self,
        result: ProcessResult,
        event_time: float,
        channel_id: int,
    ) -> NDArray[np.float64] | None:
        """Extract ±event_window_s of raw signal around the event.

        Returns an array of shape (n_window_samples,) for the given channel,
        or None if the ring buffer doesn't have enough history.
        """
        if self._event_window_s <= 0 or result.ring_buffer is None:
            return None

        sr = result.chunk.sample_rate
        half_win = int(self._event_window_s * sr)
        total_win = 2 * half_win + 1

        avail = result.ring_buffer.available
        if avail < total_win:
            return None

        try:
            # The ring buffer only supports "read last N samples".
            # The event sits within the current chunk.  We need to read
            # far enough back to cover (event - half_win) and forward
            # to the write head.
            chunk_end_time = result.chunk.timestamps[-1]
            samples_after_event = max(0, int((chunk_end_time - event_time) * sr))

            # We need half_win samples before the event and
            # half_win samples after it.  The ring buffer head is at
            # (samples_after_event) samples past the event, so we need:
            read_len = half_win + 1 + samples_after_event + half_win
            # But we only actually need the data from
            # (event - half_win) to (event + half_win), which is total_win.
            # However we must read from the head backwards, so:
            read_len = samples_after_event + half_win + 1
            # This gives us from (head - read_len) to head, and the event
            # is at position (read_len - samples_after_event - 1).
            # We need half_win samples before event_pos, so:
            # event_pos - half_win >= 0
            # (read_len - samples_after_event - 1) - half_win >= 0
            # read_len >= samples_after_event + half_win + 1
            # That's exactly what we have.  But we also need to ensure
            # we can get half_win BEFORE the event, which means we need
            # to read: samples_after_event + half_win + 1 samples.
            # AND we need half_win samples BEFORE the event in the buffer,
            # so total read must also be >= half_win (before) + 1 + samples_after.
            # Our formula is correct — the issue was only ensuring avail >= read_len.
            read_len = max(read_len, total_win)
            read_len = min(read_len, avail)

            if read_len < total_win:
                return None

            window_data = result.ring_buffer.read(read_len)

            # Find the channel index
            ch_ids = result.chunk.channel_ids
            ch_indices = np.where(ch_ids == channel_id)[0]
            if len(ch_indices) == 0:
                ch_idx = 0
            else:
                ch_idx = ch_indices[0]

            # The event sample is at position (read_len - samples_after_event - 1)
            event_pos = read_len - samples_after_event - 1
            start = max(0, event_pos - half_win)
            end = min(window_data.shape[1], event_pos + half_win + 1)

            if end - start < half_win:
                # Not enough data on one side — skip
                return None

            if ch_idx < window_data.shape[0]:
                return window_data[ch_idx, start:end].copy()
            return None
        except (ValueError, IndexError):
            return None

    def _compute_phase_diff(self, phase: NDArray, target: float) -> NDArray:
        """Vectorised circular distance from target phase."""
        diff = np.abs((phase - target) % (2 * pi))
        return np.minimum(diff, 2 * pi - diff)

    def process(self, result: ProcessResult) -> ProcessResult:
        if result.wavelet is None:
            return result

        self._chunks_seen += 1
        if self._chunks_seen <= self._warmup_chunks:
            return result

        wavelet = result.wavelet
        chunk = result.chunk

        # --- Get slow oscillation band ---
        so_mask = (
            (wavelet.frequencies >= self._freq_range[0])
            & (wavelet.frequencies <= self._freq_range[1])
        )
        if not np.any(so_mask):
            return result

        # Amplitude and phase in the SO band
        so_amplitude = np.mean(wavelet.amplitude[:, so_mask, :], axis=1)
        so_amp_per_freq = np.mean(wavelet.amplitude[:, so_mask, :], axis=2)
        so_freqs = wavelet.frequencies[so_mask]

        # --- High-frequency ratio for IED rejection ---
        hf_mask = (
            (wavelet.frequencies >= self._hf_freq_range[0])
            & (wavelet.frequencies <= self._hf_freq_range[1])
        )
        has_hf = np.any(hf_mask)
        if has_hf:
            hf_amplitude = np.mean(wavelet.amplitude[:, hf_mask, :], axis=1)

        # --- Channel selection ---
        n_wavelet_ch = wavelet.analytic.shape[0]
        if n_wavelet_ch == chunk.n_channels:
            if self._channels is not None:
                ch_mask = np.isin(chunk.channel_ids, self._channels)
                so_amplitude = so_amplitude[ch_mask]
                so_amp_per_freq = so_amp_per_freq[ch_mask]
                if has_hf:
                    hf_amplitude = hf_amplitude[ch_mask]
                ch_ids = chunk.channel_ids[ch_mask]
                analytic_so = wavelet.analytic[np.ix_(ch_mask, so_mask)]
            else:
                ch_ids = chunk.channel_ids
                analytic_so = wavelet.analytic[:, so_mask, :]
        else:
            if self._channels is not None:
                ch_mask_full = np.isin(chunk.channel_ids, self._channels)
                ch_ids = chunk.channel_ids[ch_mask_full][:n_wavelet_ch]
            else:
                ch_ids = np.arange(n_wavelet_ch, dtype=np.int32)
            analytic_so = wavelet.analytic[:, so_mask, :]

        events: list[Event] = []

        for ci in range(so_amplitude.shape[0]):
            ch_id = int(ch_ids[ci])

            # Pick dominant SO frequency for this channel
            best_freq_idx = int(np.argmax(so_amp_per_freq[ci]))
            best_freq = float(so_freqs[best_freq_idx])

            # Instantaneous phase at dominant frequency: (n_samples,)
            phase = np.angle(analytic_so[ci, best_freq_idx, :])
            phase = phase % (2 * pi)

            # Mean amplitude for this chunk
            chunk_amp = float(np.mean(so_amplitude[ci]))

            # Update amplitude history
            if ch_id not in self._amp_history:
                self._amp_history[ch_id] = []
            self._amp_history[ch_id].append(chunk_amp)
            if len(self._amp_history[ch_id]) > self._amp_smoothing:
                self._amp_history[ch_id] = self._amp_history[ch_id][-self._amp_smoothing:]
            mean_amp = float(np.mean(self._amp_history[ch_id]))

            # HF ratio (chunk-level, same for all samples)
            if has_hf:
                hf_mean = float(np.mean(hf_amplitude[ci]))
                so_mean = max(float(np.mean(so_amplitude[ci])), 1e-10)
                hf_ratio = hf_mean / so_mean
            else:
                hf_ratio = 0.0

            # ---- Vectorised phase matching ----
            phase_diff = self._compute_phase_diff(phase, self._target_phase)
            at_target = phase_diff < self._phase_tolerance

            if not np.any(at_target):
                continue

            # Get timestamps and candidate indices
            timestamps = chunk.timestamps
            candidate_indices = np.where(at_target)[0]

            # --- Check STIM2 first ---
            if ch_id in self._awaiting_stim2:
                stim1_t = self._awaiting_stim2[ch_id]

                for si in candidate_indices:
                    t = timestamps[si]
                    time_since_stim1 = t - stim1_t

                    if time_since_stim1 < self._stim2_delay_s:
                        continue
                    if time_since_stim1 > self._stim2_delay_s + self._stim2_window_s:
                        del self._awaiting_stim2[ch_id]
                        break

                    # Phase already checked by at_target mask
                    meta = {
                        "phase": float(phase[si]),
                        "frequency": best_freq,
                        "amplitude": mean_amp,
                        "stim1_time": stim1_t,
                        "delay": time_since_stim1,
                    }
                    # Capture raw signal window
                    raw_win = self._extract_event_window(result, t, ch_id)
                    if raw_win is not None:
                        meta["raw_window"] = raw_win
                        meta["raw_window_sr"] = result.chunk.sample_rate

                    events.append(Event(
                        event_type=EventType.STIM2,
                        timestamp=t,
                        channel_id=ch_id,
                        metadata=meta,
                    ))
                    del self._awaiting_stim2[ch_id]
                    logger.info(
                        "STIM2 ch=%d t=%.3fs phase=%.2f delay=%.3fs",
                        ch_id, t, float(phase[si]), time_since_stim1,
                    )
                    break
                # If still awaiting and window expired, check
                if ch_id in self._awaiting_stim2:
                    last_t = timestamps[-1]
                    if last_t - self._awaiting_stim2[ch_id] > self._stim2_delay_s + self._stim2_window_s:
                        del self._awaiting_stim2[ch_id]
                continue  # STIM2 handling done for this channel/chunk

            # --- STIM1 checks ---

            # Amplitude inhibition (chunk-level)
            if mean_amp < self._amp_min or mean_amp > self._amp_max:
                continue

            # HF ratio inhibition (chunk-level)
            if hf_ratio > self._hf_ratio_max:
                continue

            # Backoff (find first candidate after backoff)
            last_stim = self._last_stim1_time.get(ch_id, -np.inf)

            for si in candidate_indices:
                t = timestamps[si]
                if t - last_stim < self._backoff_s:
                    continue

                meta = {
                    "phase": float(phase[si]),
                    "frequency": best_freq,
                    "amplitude": mean_amp,
                    "hf_ratio": hf_ratio,
                    "threshold_amp_min": self._amp_min,
                    "threshold_amp_max": self._amp_max,
                }
                # Capture raw signal window
                raw_win = self._extract_event_window(result, t, ch_id)
                if raw_win is not None:
                    meta["raw_window"] = raw_win
                    meta["raw_window_sr"] = result.chunk.sample_rate

                events.append(Event(
                    event_type=EventType.STIM1,
                    timestamp=t,
                    channel_id=ch_id,
                    metadata=meta,
                ))
                self._last_stim1_time[ch_id] = t
                self._awaiting_stim2[ch_id] = t
                logger.info(
                    "STIM1 ch=%d t=%.3fs phase=%.2f freq=%.2fHz amp=%.1f hf_ratio=%.3f",
                    ch_id, t, float(phase[si]), best_freq, mean_amp, hf_ratio,
                )
                break  # one STIM1 per chunk per channel

        result.events.extend(events)
        return result

    def reset(self) -> None:
        self._chunks_seen = 0
        self._last_stim1_time.clear()
        self._awaiting_stim2.clear()
        self._amp_history.clear()
