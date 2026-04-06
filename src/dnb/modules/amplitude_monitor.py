"""Amplitude monitor — inhibition detector.

This is the "inhibition detector" in the Rust architecture. It watches
mean amplitude in a frequency band and sets a flag when it's above
threshold — indicating an IED or artefact that should block stimulation.

Simple by design: just "is the power in this band too high right now?"

Stores results in result.detections[self.id]:
    {
        "active": bool,         # inhibition triggered this chunk
        "amplitude": float,     # mean amplitude in the monitored band
        "ratio": float,         # ratio of HF to reference band (if ref provided)
    }
"""

from __future__ import annotations

import logging

import numpy as np

from dnb.core.types import PipelineConfig
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


class AmplitudeMonitor(Module):
    """Simple amplitude threshold monitor for a frequency band.

    Use for IED detection / stimulus inhibition: configure with a
    high-frequency band and a threshold. When mean amplitude exceeds
    the threshold, the monitor sets active=True.

    Can also compute a ratio against a reference band (e.g. HF/LF ratio
    for IED rejection in the Rust sense).

    Args:
        id: Unique identifier for this detector.
        freq_range: (low_hz, high_hz) band to monitor.
        threshold: Absolute amplitude threshold. If exceeded, active=True.
        ref_freq_range: Optional reference band for ratio computation.
        ratio_max: If ratio mode is used, max HF/ref ratio before inhibit.
        warmup_chunks: Initial chunks to skip.
    """

    def __init__(
        self,
        id: str = "ied_monitor",
        freq_range: tuple[float, float] = (10.0, 40.0),
        threshold: float | None = None,
        ref_freq_range: tuple[float, float] | None = None,
        ratio_max: float = 0.5,
        warmup_chunks: int = 5,
    ) -> None:
        self.id = id
        self._freq_range = freq_range
        self._threshold = threshold
        self._ref_freq_range = ref_freq_range
        self._ratio_max = ratio_max
        self._warmup_chunks = warmup_chunks
        self._chunks_seen: int = 0

    def configure(self, config: PipelineConfig) -> None:
        mode = "ratio" if self._ref_freq_range else "absolute"
        logger.info(
            "AmplitudeMonitor '%s': freq=(%.1f, %.1f) Hz, mode=%s",
            self.id, self._freq_range[0], self._freq_range[1], mode,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        if result.wavelet is None:
            result.detections[self.id] = {"active": False, "amplitude": 0.0}
            return result

        self._chunks_seen += 1
        if self._chunks_seen <= self._warmup_chunks:
            result.detections[self.id] = {"active": False, "amplitude": 0.0, "warming_up": True}
            return result

        wavelet = result.wavelet

        # Get amplitude in our monitored band
        hf_mask = (
            (wavelet.frequencies >= self._freq_range[0])
            & (wavelet.frequencies <= self._freq_range[1])
        )
        if not np.any(hf_mask):
            result.detections[self.id] = {"active": False, "amplitude": 0.0}
            return result

        hf_amp = float(np.mean(wavelet.amplitude[:, hf_mask, :]))

        # Ratio mode: compare to reference band
        if self._ref_freq_range is not None:
            ref_mask = (
                (wavelet.frequencies >= self._ref_freq_range[0])
                & (wavelet.frequencies <= self._ref_freq_range[1])
            )
            if np.any(ref_mask):
                ref_amp = max(float(np.mean(wavelet.amplitude[:, ref_mask, :])), 1e-10)
                ratio = hf_amp / ref_amp
                active = ratio > self._ratio_max
                result.detections[self.id] = {
                    "active": active,
                    "amplitude": hf_amp,
                    "ratio": ratio,
                }
                return result

        # Absolute threshold mode
        if self._threshold is not None:
            active = hf_amp > self._threshold
        else:
            active = False

        result.detections[self.id] = {"active": active, "amplitude": hf_amp}
        return result

    def reset(self) -> None:
        self._chunks_seen = 0
