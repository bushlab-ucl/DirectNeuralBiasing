"""TWave-style SO detector — phase at most recent sample, predict forward.

Replaces TargetWaveDetector. Instead of scanning a chunk for phase
crossings, this module:

    1. Reads phase/freq/amplitude at the MOST RECENT sample from the
       wavelet output (the trailing edge of the convolution).
    2. Computes time until target phase arrives.
    3. If that time is within the prediction limit, validates the
       detection using multi-feature criteria (TWave-style).
    4. Emits a candidate with the exact predicted timestamp.

Multi-feature validation (from TWave paper, Li et al. 2025):
    - Amplitude within physiological bounds (75–300 µV)
    - High-to-low frequency ratio < threshold (rejects IEDs/artifacts)
    - Template match: dot product of recent signal vs ideal sinusoid

This eliminates: phase tolerance parameters, crossing detection,
wrap-artifact rejection, chunk-boundary sensitivity. The detection
is one comparison per chunk, not a scan.
"""

from __future__ import annotations

import logging
from math import pi

import numpy as np
from numpy.typing import NDArray

from dnb.core.types import PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class TWaveDetector(Module):
    """TWave-style slow oscillation detector.

    Args:
        id: Detector identifier (used by StimTrigger to find this detector).
        freq_range: (lo, hi) Hz — which wavelet frequencies count as "SO".
        target_phase: Phase to predict forward to (0 = peak, π = trough).
        prediction_limit_s: Max lookahead in seconds (TWave uses 0.15).
        amp_min: Minimum SO amplitude in µV (TWave: 75).
        amp_max: Maximum SO amplitude in µV (TWave: 300).
        hilo_ratio_max: Max ratio of high-freq to low-freq wavelet power
            (TWave: 0.15). Set None to disable.
        hilo_boundary_hz: Frequency boundary for hi/lo ratio calculation.
        template_threshold: Min dot-product match against ideal sinusoid
            (TWave: 0.8). Set None to disable.
        template_window_s: Seconds of signal history for template matching.
        warmup_chunks: Chunks to skip before detection (buffer filling).
    """

    def __init__(
        self,
        id: str = "slow_wave",
        freq_range: tuple[float, float] = (0.5, 2.0),
        target_phase: float = 0.0,
        prediction_limit_s: float = 0.15,
        amp_min: float = 75.0,
        amp_max: float = 300.0,
        hilo_ratio_max: float | None = 0.15,
        hilo_boundary_hz: float = 10.0,
        template_threshold: float | None = 0.8,
        template_window_s: float = 2.0,
        warmup_chunks: int = 20,
    ) -> None:
        self.id = id
        self._freq_range = freq_range
        self._target_phase = target_phase % (2 * pi)
        self._prediction_limit_s = prediction_limit_s
        self._amp_min = amp_min
        self._amp_max = amp_max
        self._hilo_ratio_max = hilo_ratio_max
        self._hilo_boundary_hz = hilo_boundary_hz
        self._template_threshold = template_threshold
        self._template_window_s = template_window_s
        self._warmup_chunks = warmup_chunks
        self._chunks_seen = 0

    def configure(self, config: PipelineConfig) -> None:
        logger.info(
            "TWaveDetector '%s': freq=(%.1f,%.1f), target_phase=%.2f rad (%.0f°), "
            "predict_limit=%.0f ms, amp=[%.0f,%.0f] µV",
            self.id, *self._freq_range, self._target_phase,
            self._target_phase * 180 / pi,
            self._prediction_limit_s * 1000,
            self._amp_min, self._amp_max,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        self._chunks_seen += 1

        if result.wavelet is None or not result.wavelet_settled:
            result.detections[self.id] = {"active": False, "candidates": []}
            return result

        if self._chunks_seen <= self._warmup_chunks:
            result.detections[self.id] = {"active": False, "candidates": [], "warming_up": True}
            return result

        wavelet = result.wavelet
        chunk = result.chunk
        freqs = wavelet.frequencies

        # ── 1. Extract phase & amplitude at the MOST RECENT sample ────
        # analytic shape: (n_freqs, n_samples)
        # Last sample = trailing edge of convolution = "now"
        analytic_now = wavelet.analytic[:, -1]  # (n_freqs,)
        amp_now = np.abs(analytic_now)           # (n_freqs,)

        # Mask to SO frequency range
        so_mask = (freqs >= self._freq_range[0]) & (freqs <= self._freq_range[1])
        if not np.any(so_mask):
            result.detections[self.id] = {"active": False, "candidates": []}
            return result

        so_amps = amp_now[so_mask]
        so_freqs = freqs[so_mask]

        # Dominant frequency = highest amplitude in SO band at this instant
        best_idx = int(np.argmax(so_amps))
        freq_now = float(so_freqs[best_idx])
        amplitude = float(so_amps[best_idx])
        phase_now = float(np.angle(analytic_now[so_mask][best_idx])) % (2 * pi)

        # Current time = timestamp of last sample in chunk
        t_now = float(chunk.timestamps[-1])

        # ── 2. Predict time to target phase ───────────────────────────
        delta_phi = (self._target_phase - phase_now) % (2 * pi)
        if delta_phi < 1e-6:
            delta_phi = 2 * pi  # target is ~now, wait for next cycle

        dt = delta_phi / (2 * pi * freq_now)

        # If target is too far out, don't predict — unreliable
        if dt > self._prediction_limit_s:
            result.detections[self.id] = {
                "active": False, "candidates": [],
                "phase_now": phase_now, "freq_now": freq_now,
                "amplitude": amplitude, "dt": dt,
                "reject_reason": "prediction_limit",
            }
            return result

        # ── 3. Multi-feature validation ───────────────────────────────

        # (a) Amplitude bounds
        if amplitude < self._amp_min or amplitude > self._amp_max:
            result.detections[self.id] = {
                "active": False, "candidates": [],
                "phase_now": phase_now, "freq_now": freq_now,
                "amplitude": amplitude, "dt": dt,
                "reject_reason": "amplitude",
            }
            return result

        # (b) High-to-low frequency ratio (IED rejection)
        if self._hilo_ratio_max is not None:
            hi_mask = freqs >= self._hilo_boundary_hz
            lo_mask = freqs < self._hilo_boundary_hz
            if np.any(hi_mask) and np.any(lo_mask):
                hi_power = float(np.mean(amp_now[hi_mask]))
                lo_power = float(np.mean(amp_now[lo_mask]))
                ratio = hi_power / lo_power if lo_power > 0 else float("inf")
                if ratio > self._hilo_ratio_max:
                    result.detections[self.id] = {
                        "active": False, "candidates": [],
                        "phase_now": phase_now, "freq_now": freq_now,
                        "amplitude": amplitude, "dt": dt,
                        "reject_reason": "hilo_ratio",
                        "hilo_ratio": ratio,
                    }
                    return result

        # (c) Template matching — dot product of recent signal vs ideal SO
        if self._template_threshold is not None and result.ring_buffer is not None:
            template_samples = int(self._template_window_s * chunk.sample_rate)
            if result.ring_buffer.available >= template_samples:
                recent = result.ring_buffer.read_latest(template_samples)

                # Normalize
                recent_norm = recent - np.mean(recent)
                r_std = np.std(recent_norm)
                if r_std > 0:
                    recent_norm /= r_std

                    # Generate ideal sinusoid at detected frequency and phase
                    t_template = np.arange(template_samples) / chunk.sample_rate
                    # Phase at the start of the template window:
                    #   phase_now is at the end, so rewind by template duration
                    phase_start = phase_now - 2 * pi * freq_now * self._template_window_s
                    ideal = np.cos(2 * pi * freq_now * t_template + phase_start)

                    # Normalized dot product
                    match_score = float(np.dot(recent_norm, ideal) / template_samples)

                    if match_score < self._template_threshold:
                        result.detections[self.id] = {
                            "active": False, "candidates": [],
                            "phase_now": phase_now, "freq_now": freq_now,
                            "amplitude": amplitude, "dt": dt,
                            "reject_reason": "template",
                            "template_score": match_score,
                        }
                        return result

        # ── 4. All checks passed — emit candidate ────────────────────
        t_predicted = t_now + dt

        candidate = {
            "timestamp": t_predicted,
            "frequency": freq_now,
            "amplitude": amplitude,
            "phase_now": phase_now,
            "dt_to_target_ms": dt * 1000,
            "channel_id": chunk.channel_id,
        }

        result.detections[self.id] = {
            "active": True,
            "candidates": [candidate],
            "phase_now": phase_now,
            "freq_now": freq_now,
            "amplitude": amplitude,
        }
        return result

    def reset(self) -> None:
        self._chunks_seen = 0