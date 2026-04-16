"""Target wave detector — activation detector for phase-targeted events.

This is the "activation detector" in the pipeline. It watches the
wavelet phase in a configurable frequency band and flags samples where
the phase hits a **detection** angle with sufficient amplitude.

IMPORTANT DISTINCTION:
    detection_phase  — the phase at which we *detect* the slow wave
                       (default 3π/2 = rising zero crossing, giving
                       a quarter-period of lead time to schedule the
                       stim at the upcoming positive peak)
    stim_phase       — the phase at which we *want to stimulate*
                       (default 0 = positive peak, set on StimTrigger)

Phase map (for sin-convention signals):
    0      = positive peak
    π/2    = falling zero crossing
    π      = trough (negative peak)
    3π/2   = rising zero crossing  ← default detection point
    2π/0   = positive peak (stim target)

Detecting at 3π/2 gives quarter-period lead time:
    At 1 Hz:   250 ms before the peak
    At 0.5 Hz: 500 ms before the peak

The detector only cares about detection_phase. It emits candidates
with enough metadata (phase, frequency, timestamp) for the StimTrigger
to predict when stim_phase will occur.

v2 changes:
    - Removed amplitude smoothing across chunks. The wavelet's Gaussian
      envelope already provides temporal smoothing; additional chunk-level
      smoothing delayed detection of transient slow waves and has no
      equivalent in the TWave algorithm (Wong et al., Li et al.).
    - Amplitude gating now uses instantaneous (per-chunk) wavelet
      amplitude, matching the TWave approach.

Stores results in result.detections[self.id]:
    {
        "active": bool,
        "candidates": [...],
        "mean_amplitude": float,
    }

Each candidate dict:
    {
        "sample_idx": int,
        "timestamp": float,
        "phase": float,           # actual phase at detection
        "frequency": float,       # instantaneous dominant frequency
        "amplitude": float,       # instantaneous wavelet amplitude
        "channel_id": int,
    }
"""

from __future__ import annotations

import logging
from math import pi

import numpy as np

from dnb.core.types import PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class TargetWaveDetector(Module):
    """Wavelet-based phase detector for a target frequency band.

    Monitors instantaneous phase in a specified band and flags samples
    where phase matches the detection_phase within tolerance and
    amplitude is within bounds.

    Args:
        id: Unique identifier for this detector.
        freq_range: (low_hz, high_hz) band to monitor.
        detection_phase: Phase angle to detect at (radians).
            Default 3π/2 (rising zero crossing) — gives a
            quarter-period of lead time to predict and schedule
            the upcoming positive peak for stimulation.
        phase_tolerance: Half-width of phase window (radians).
        amp_min: Minimum amplitude to accept.
        amp_max: Maximum amplitude (artifact rejection).
        warmup_chunks: Initial chunks for baseline (no detections).
        channels: Which channels to monitor. None = all.
        amp_smoothing: DEPRECATED — ignored. Kept for config
            compatibility. Amplitude gating uses instantaneous values.
    """

    def __init__(
        self,
        id: str = "slow_wave",
        freq_range: tuple[float, float] = (0.5, 2.0),
        detection_phase: float = 3 * pi / 2,
        phase_tolerance: float = 0.15,
        amp_min: float = 50.0,
        amp_max: float = 10000.0,
        warmup_chunks: int = 10,
        channels: list[int] | None = None,
        amp_smoothing: int | None = None,  # deprecated, ignored
    ) -> None:
        self.id = id
        self._freq_range = freq_range
        self._detection_phase = detection_phase % (2 * pi)
        self._phase_tolerance = phase_tolerance
        self._amp_min = amp_min
        self._amp_max = amp_max
        self._warmup_chunks = warmup_chunks
        self._channels = channels

        self._chunks_seen: int = 0

        if amp_smoothing is not None:
            logger.info(
                "TargetWaveDetector '%s': amp_smoothing=%d is deprecated "
                "and ignored. Using instantaneous amplitude.",
                id, amp_smoothing,
            )

    def configure(self, config: PipelineConfig) -> None:
        logger.info(
            "TargetWaveDetector '%s': freq=(%.1f, %.1f) Hz, "
            "detection_phase=%.2f rad (%.0f°), amp=(%.0f, %.0f)",
            self.id, self._freq_range[0], self._freq_range[1],
            self._detection_phase, self._detection_phase * 180 / pi,
            self._amp_min, self._amp_max,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        if result.wavelet is None or not result.wavelet_settled:
            result.detections[self.id] = {"active": False, "candidates": []}
            return result

        self._chunks_seen += 1
        if self._chunks_seen <= self._warmup_chunks:
            result.detections[self.id] = {"active": False, "candidates": [], "warming_up": True}
            return result

        wavelet = result.wavelet
        chunk = result.chunk

        # Find frequency indices in our target band
        so_mask = (
            (wavelet.frequencies >= self._freq_range[0])
            & (wavelet.frequencies <= self._freq_range[1])
        )
        if not np.any(so_mask):
            result.detections[self.id] = {"active": False, "candidates": []}
            return result

        # Amplitude and analytic signal in our band
        so_amplitude = np.mean(wavelet.amplitude[:, so_mask, :], axis=1)  # (n_ch, n_samples)
        so_amp_per_freq = np.mean(wavelet.amplitude[:, so_mask, :], axis=2)  # (n_ch, n_so_freqs)
        so_freqs = wavelet.frequencies[so_mask]

        # Channel selection
        n_wavelet_ch = wavelet.analytic.shape[0]
        if n_wavelet_ch == chunk.n_channels and self._channels is not None:
            ch_mask = np.isin(chunk.channel_ids, self._channels)
            so_amplitude = so_amplitude[ch_mask]
            so_amp_per_freq = so_amp_per_freq[ch_mask]
            ch_ids = chunk.channel_ids[ch_mask]
            analytic_so = wavelet.analytic[np.ix_(ch_mask, so_mask)]
        elif self._channels is not None:
            ch_ids = chunk.channel_ids[:n_wavelet_ch]
            analytic_so = wavelet.analytic[:, so_mask, :]
        else:
            ch_ids = chunk.channel_ids if n_wavelet_ch == chunk.n_channels else np.arange(n_wavelet_ch, dtype=np.int32)
            analytic_so = wavelet.analytic[:, so_mask, :]

        candidates = []

        for ci in range(so_amplitude.shape[0]):
            ch_id = int(ch_ids[ci])

            # Pick dominant frequency for this channel (highest amplitude)
            best_freq_idx = int(np.argmax(so_amp_per_freq[ci]))
            best_freq = float(so_freqs[best_freq_idx])

            # Phase at dominant frequency
            phase = np.angle(analytic_so[ci, best_freq_idx, :]) % (2 * pi)

            # Instantaneous amplitude — use the chunk mean at dominant freq.
            # This is the wavelet envelope amplitude, already temporally
            # smoothed by the Morlet Gaussian window. No additional
            # cross-chunk smoothing needed.
            chunk_amp = float(np.mean(so_amplitude[ci]))

            # Amplitude gating (instantaneous, no smoothing)
            if chunk_amp < self._amp_min or chunk_amp > self._amp_max:
                continue

            # Phase matching against detection_phase
            phase_diff = np.abs((phase - self._detection_phase) % (2 * pi))
            phase_diff = np.minimum(phase_diff, 2 * pi - phase_diff)
            at_target = phase_diff < self._phase_tolerance
            candidate_indices = np.where(at_target)[0]

            for si in candidate_indices:
                candidates.append({
                    "sample_idx": int(si),
                    "timestamp": float(chunk.timestamps[si]),
                    "phase": float(phase[si]),
                    "frequency": best_freq,
                    "amplitude": chunk_amp,
                    "channel_id": ch_id,
                })

        result.detections[self.id] = {
            "active": len(candidates) > 0,
            "candidates": candidates,
            "mean_amplitude": float(np.mean(so_amplitude)) if so_amplitude.size > 0 else 0.0,
        }
        return result

    def reset(self) -> None:
        self._chunks_seen = 0