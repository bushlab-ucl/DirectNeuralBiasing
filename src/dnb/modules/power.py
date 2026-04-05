"""Power estimation module using wavelet decomposition output.

Computes instantaneous and windowed band power from the WaveletResult,
useful for closed-loop feedback based on oscillatory power.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from dnb.core.types import PipelineConfig
from dnb.modules.base import Module, ProcessResult


class PowerEstimator(Module):
    """Estimate band-specific power from wavelet amplitude.

    Computes mean power within specified frequency bands per channel,
    storing results in ProcessResult.data for downstream modules.

    Args:
        bands: Named frequency bands as {name: (low_hz, high_hz)}.
            Defaults to standard neural oscillation bands.
    """

    def __init__(
        self,
        bands: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        self._bands = bands or {
            "delta": (1.0, 4.0),
            "theta": (4.0, 8.0),
            "alpha": (8.0, 13.0),
            "beta": (13.0, 30.0),
            "low_gamma": (30.0, 80.0),
            "high_gamma": (80.0, 200.0),
        }

    def configure(self, config: PipelineConfig) -> None:
        pass

    def process(self, result: ProcessResult) -> ProcessResult:
        if result.wavelet is None:
            return result

        wavelet = result.wavelet

        for name, (lo, hi) in self._bands.items():
            freq_mask = (wavelet.frequencies >= lo) & (wavelet.frequencies <= hi)
            if not np.any(freq_mask):
                continue

            # Mean power across frequencies in this band: (n_channels, n_samples)
            band_power = np.mean(wavelet.power[:, freq_mask, :], axis=1)

            # Store both instantaneous and chunk-averaged
            result.data[f"power_{name}"] = band_power
            result.data[f"power_{name}_mean"] = np.mean(band_power, axis=1)

        return result

    def reset(self) -> None:
        pass
