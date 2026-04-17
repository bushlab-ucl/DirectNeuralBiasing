"""Target wave detector — single channel, crossing-based phase detection.

Detects when the wavelet phase crosses detection_phase within a chunk.
Uses wrap-artifact rejection (real crossings have small phase_diff on
both sides; wrap artifacts have ~±π) to distinguish true crossings
from 2π boundary effects.

Amplitude gating uses a rolling z-score (Welford's algorithm).
"""

from __future__ import annotations

import logging
from math import pi

import numpy as np

from dnb.core.types import PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class _RollingStats:
    """Welford's online mean/std."""
    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self._m2 = 0.0

    def update(self, value: float) -> None:
        self.count += 1
        d = value - self.mean
        self.mean += d / self.count
        self._m2 += d * (value - self.mean)

    @property
    def std(self) -> float:
        return (self._m2 / self.count) ** 0.5 if self.count > 1 else 0.0

    def z_score(self, value: float) -> float:
        s = self.std
        return (value - self.mean) / s if s > 0 else 0.0


class TargetWaveDetector(Module):
    def __init__(
        self,
        id: str = "slow_wave",
        freq_range: tuple[float, float] = (0.5, 2.0),
        detection_phase: float = pi,
        phase_tolerance: float = 0.5,
        z_score_threshold: float = 1.0,
        amp_min: float | None = None,
        amp_max: float = 10000.0,
        warmup_chunks: int = 10,
        # Compat params (ignored)
        channels: list[int] | None = None,
        amp_smoothing: int | None = None,
    ) -> None:
        self.id = id
        self._freq_range = freq_range
        self._detection_phase = detection_phase % (2 * pi)
        self._phase_tolerance = phase_tolerance
        self._z_score_threshold = z_score_threshold
        self._amp_min = amp_min
        self._amp_max = amp_max
        self._warmup_chunks = warmup_chunks
        self._use_z_score = amp_min is None
        self._chunks_seen: int = 0
        self._stats = _RollingStats()

    def configure(self, config: PipelineConfig) -> None:
        mode = f"z>{self._z_score_threshold}" if self._use_z_score else f"amp[{self._amp_min},{self._amp_max}]"
        logger.info(
            "TargetWaveDetector '%s': freq=(%.1f,%.1f), det_phase=%.2frad (%.0f°), %s",
            self.id, *self._freq_range, self._detection_phase,
            self._detection_phase * 180 / pi, mode,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        if result.wavelet is None or not result.wavelet_settled:
            result.detections[self.id] = {"active": False, "candidates": []}
            return result

        self._chunks_seen += 1
        wavelet = result.wavelet
        chunk = result.chunk

        so_mask = (
            (wavelet.frequencies >= self._freq_range[0])
            & (wavelet.frequencies <= self._freq_range[1])
        )
        if not np.any(so_mask):
            result.detections[self.id] = {"active": False, "candidates": []}
            return result

        # Single channel: (n_so_freqs, n_samples)
        so_amp = wavelet.amplitude[so_mask, :]
        so_freqs = wavelet.frequencies[so_mask]

        amp_per_freq = np.mean(so_amp, axis=1)
        best_freq_idx = int(np.argmax(amp_per_freq))
        best_freq = float(so_freqs[best_freq_idx])

        phase = np.angle(wavelet.analytic[so_mask][best_freq_idx, :]) % (2 * pi)
        chunk_amp = float(np.mean(so_amp))

        self._stats.update(chunk_amp)

        if self._chunks_seen <= self._warmup_chunks:
            result.detections[self.id] = {"active": False, "candidates": [], "warming_up": True}
            return result

        # Amplitude gating
        if self._use_z_score:
            z = self._stats.z_score(chunk_amp)
            if z < self._z_score_threshold:
                result.detections[self.id] = {"active": False, "candidates": []}
                return result
        else:
            if chunk_amp < self._amp_min or chunk_amp > self._amp_max:
                result.detections[self.id] = {"active": False, "candidates": []}
                return result

        # --- Crossing detection ---
        # Find where the phase crosses detection_phase within this chunk.
        # Compute signed distance to target, find sign changes.
        phase_diff = self._signed_phase_diff_array(phase)
        signs = np.sign(phase_diff)
        crossings = np.where(np.diff(signs) != 0)[0]

        candidates = []
        for ci in crossings:
            # Pick the sample closer to the target phase
            si = ci if abs(phase_diff[ci]) <= abs(phase_diff[ci + 1]) else ci + 1

            # Reject wrap artifacts: a real crossing has small phase_diff
            # on both sides. A wrap (e.g. 2π boundary) has ~±π.
            if abs(phase_diff[ci]) > 1.0 or abs(phase_diff[ci + 1]) > 1.0:
                continue

            if abs(phase_diff[si]) > self._phase_tolerance:
                continue

            candidates.append({
                "sample_idx": int(si),
                "timestamp": float(chunk.timestamps[si]),
                "phase": float(phase[si]),
                "frequency": best_freq,
                "amplitude": chunk_amp,
                "z_score": self._stats.z_score(chunk_amp),
                "channel_id": chunk.channel_id,
            })

        result.detections[self.id] = {
            "active": len(candidates) > 0,
            "candidates": candidates,
            "mean_amplitude": chunk_amp,
        }
        return result

    def _signed_phase_diff_array(self, phase: np.ndarray) -> np.ndarray:
        """Vectorized signed distance from phase array to detection_phase."""
        d = (phase - self._detection_phase) % (2 * pi)
        return np.where(d > pi, d - 2 * pi, d)

    def reset(self) -> None:
        self._chunks_seen = 0
        self._stats = _RollingStats()