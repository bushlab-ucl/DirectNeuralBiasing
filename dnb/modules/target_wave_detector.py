"""Target wave detector — activation detector for phase-targeted events.

This is the "activation detector" in the pipeline. It watches the
wavelet phase in a configurable frequency band and flags samples where
the phase hits a **detection** angle with sufficient amplitude.

IMPORTANT DISTINCTION:
    detection_phase  — the phase at which we *detect* the slow wave
    stim_phase       — the phase at which we *want to stimulate*
                       (set on StimTrigger, not here)

Phase map (for sin-convention signals):
    0      = positive peak
    π/2    = falling zero crossing
    π      = trough (negative peak)
    3π/2   = rising zero crossing
    2π/0   = positive peak (stim target)

Amplitude gating uses a rolling z-score baseline (matching the Rust
Statistics struct). This adapts to any recording's amplitude scale
automatically — no hand-tuned thresholds needed. The wavelet's
Gaussian envelope already provides temporal smoothing; no additional
cross-chunk smoothing is applied.

Stores results in result.detections[self.id]:
    {
        "active": bool,
        "candidates": [...],
        "mean_amplitude": float,
    }
"""

from __future__ import annotations

import logging
from math import pi

import numpy as np

from dnb.core.types import PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class _RollingStats:
    """Running mean/std tracker (Welford's online algorithm)."""

    def __init__(self) -> None:
        self.count: int = 0
        self.mean: float = 0.0
        self._m2: float = 0.0

    def update(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self._m2 += delta * delta2

    @property
    def std(self) -> float:
        if self.count < 2:
            return 0.0
        return (self._m2 / self.count) ** 0.5

    def z_score(self, value: float) -> float:
        s = self.std
        if s == 0.0:
            return 0.0
        return (value - self.mean) / s


class TargetWaveDetector(Module):
    """Wavelet-based phase detector for a target frequency band.

    Monitors instantaneous phase in a specified band and flags samples
    where phase matches the detection_phase within tolerance and
    amplitude z-score exceeds threshold.

    Args:
        id: Unique identifier for this detector.
        freq_range: (low_hz, high_hz) band to monitor.
        detection_phase: Phase angle to detect at (radians).
        phase_tolerance: Half-width of phase window (radians).
        z_score_threshold: Minimum amplitude z-score to accept.
            Uses rolling baseline. Replaces the old fixed amp_min/amp_max.
        amp_min: DEPRECATED — kept for config compatibility.
            If z_score_threshold is not set, falls back to fixed thresholds.
        amp_max: DEPRECATED — maximum amplitude (artifact rejection).
        warmup_chunks: Initial chunks for baseline (no detections).
    """

    def __init__(
        self,
        id: str = "slow_wave",
        freq_range: tuple[float, float] = (0.5, 2.0),
        detection_phase: float = pi,
        phase_tolerance: float = 0.05,
        z_score_threshold: float = 1.0,
        amp_min: float | None = None,
        amp_max: float = 10000.0,
        warmup_chunks: int = 10,
        channels: list[int] | None = None,
        # Deprecated params kept for config compat
        amp_smoothing: int | None = None,
    ) -> None:
        self.id = id
        self._freq_range = freq_range
        self._detection_phase = detection_phase % (2 * pi)
        self._phase_tolerance = phase_tolerance
        self._z_score_threshold = z_score_threshold
        self._amp_min = amp_min  # fallback only
        self._amp_max = amp_max
        self._warmup_chunks = warmup_chunks
        self._channels = channels

        self._chunks_seen: int = 0
        self._stats = _RollingStats()

        # Decide gating mode
        self._use_z_score = amp_min is None
        if not self._use_z_score:
            logger.info(
                "TargetWaveDetector '%s': using fixed amplitude thresholds "
                "(amp_min=%.0f, amp_max=%.0f). Consider switching to "
                "z_score_threshold for adaptive gating.",
                id, amp_min, amp_max,
            )

    def configure(self, config: PipelineConfig) -> None:
        mode = (
            f"z_score > {self._z_score_threshold}"
            if self._use_z_score
            else f"amp in [{self._amp_min}, {self._amp_max}]"
        )
        logger.info(
            "TargetWaveDetector '%s': freq=(%.1f, %.1f) Hz, "
            "detection_phase=%.2f rad (%.0f°), gating=%s",
            self.id, self._freq_range[0], self._freq_range[1],
            self._detection_phase, self._detection_phase * 180 / pi,
            mode,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        if result.wavelet is None or not result.wavelet_settled:
            result.detections[self.id] = {"active": False, "candidates": []}
            return result

        self._chunks_seen += 1
        if self._chunks_seen <= self._warmup_chunks:
            # Still update stats during warmup
            wavelet = result.wavelet
            so_mask = (
                (wavelet.frequencies >= self._freq_range[0])
                & (wavelet.frequencies <= self._freq_range[1])
            )
            if np.any(so_mask):
                so_amplitude = np.mean(wavelet.amplitude[:, so_mask, :], axis=1)
                chunk_amp = float(np.mean(so_amplitude))
                self._stats.update(chunk_amp)

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

            # Instantaneous amplitude — chunk mean at dominant freq
            chunk_amp = float(np.mean(so_amplitude[ci]))

            # Update rolling stats and check amplitude
            self._stats.update(chunk_amp)

            if self._use_z_score:
                # Z-score based gating (adaptive, like Rust detector)
                z = self._stats.z_score(chunk_amp)
                if z < self._z_score_threshold:
                    continue
                # No upper bound in z-score mode — artifact rejection is
                # handled by the AmplitudeMonitor (IED inhibition)
            else:
                # Fixed threshold fallback
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
                    "z_score": self._stats.z_score(chunk_amp),
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
        self._stats = _RollingStats()