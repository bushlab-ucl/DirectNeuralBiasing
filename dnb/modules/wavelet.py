"""Wavelet convolution module for time-frequency decomposition.

Complex Morlet wavelets with log-spaced centre frequencies and 1/f
scaling. Single-pass replacement for traditional bandpass filter banks.

This is the equivalent of the Rust "filter" stage, but instead of
producing one filtered signal per band, it produces the full analytic
signal at every (channel, frequency, time) point. Detectors downstream
can then read amplitude, phase, or power in whatever band they need.
"""

from __future__ import annotations

import logging

import numpy as np
from numpy.typing import NDArray
from scipy.fft import fft, ifft, next_fast_len

from dnb.core.types import DataChunk, PipelineConfig, WaveletResult
from dnb.modules.base import Module, ProcessResult

logger = logging.getLogger(__name__)


def _make_morlet_kernel(
    freq: float, n_cycles: float, sample_rate: float, n_fft: int,
) -> NDArray[np.complex128]:
    """Create a complex Morlet wavelet kernel in frequency domain (zero-phase)."""
    sigma = n_cycles / (2.0 * np.pi * freq)
    half_len = int(4.0 * sigma * sample_rate)
    t = np.arange(-half_len, half_len + 1) / sample_rate

    wavelet = np.exp(2j * np.pi * freq * t) * np.exp(-(t ** 2) / (2.0 * sigma ** 2))
    wavelet /= np.sqrt(np.sum(np.abs(wavelet) ** 2))

    # Wrap kernel so t=0 is at index 0 (zero-phase alignment).
    # Positive-time part at start, negative-time part wraps to end.
    kernel = np.zeros(n_fft, dtype=np.complex128)
    kernel[:half_len + 1] = wavelet[half_len:]
    kernel[n_fft - half_len:] = wavelet[:half_len]
    return fft(kernel)


class WaveletConvolution(Module):
    """Log-spaced, 1/f-scaled complex Morlet wavelet decomposition.

    Produces a WaveletResult with the full analytic signal. Downstream
    detectors read .amplitude, .phase, .power in their target bands.

    Uses overlap-save when a ring buffer is available to eliminate
    edge artefacts at chunk boundaries.

    Args:
        freq_min: Lowest centre frequency in Hz.
        freq_max: Highest centre frequency in Hz.
        n_freqs: Number of log-spaced frequency bins.
        n_cycles_base: Cycles at freq_min (scales with frequency).
        channels: Which channels to decompose. None = all.
    """

    def __init__(
        self,
        freq_min: float = 0.5,
        freq_max: float = 30.0,
        n_freqs: int = 10,
        n_cycles_base: float = 3.0,
        channels: list[int] | None = None,
    ) -> None:
        self._freq_min = freq_min
        self._freq_max = freq_max
        self._n_freqs = n_freqs
        self._n_cycles_base = n_cycles_base
        self._channels = channels

        self._frequencies: NDArray[np.float64] | None = None
        self._n_cycles: NDArray[np.float64] | None = None
        self._kernels_fft: list[NDArray[np.complex128]] = []
        self._n_fft: int = 0
        self._sample_rate: float = 0.0
        self._max_kernel_len: int = 0
        self._overlap: int = 0

    @property
    def frequencies(self) -> NDArray[np.float64]:
        if self._frequencies is None:
            raise RuntimeError("Module not configured yet.")
        return self._frequencies

    def configure(self, config: PipelineConfig) -> None:
        self._sample_rate = config.sample_rate
        self._frequencies = np.geomspace(self._freq_min, self._freq_max, self._n_freqs)
        self._n_cycles = self._n_cycles_base * (self._frequencies / self._freq_min)

        max_kernel_len = 0
        for freq, nc in zip(self._frequencies, self._n_cycles):
            sigma = nc / (2.0 * np.pi * freq)
            kernel_len = 2 * int(4.0 * sigma * self._sample_rate) + 1
            max_kernel_len = max(max_kernel_len, kernel_len)
        self._max_kernel_len = max_kernel_len
        self._overlap = (max_kernel_len - 1) // 2

        self._min_warmup_chunks = int(np.ceil(
            (self._overlap + config.chunk_samples) / config.chunk_samples
        ))

        self._n_fft = next_fast_len(config.chunk_samples + self._max_kernel_len - 1)
        self._precompute_kernels()

        logger.info(
            "WaveletConvolution: %d freqs (%.1f–%.1f Hz), overlap=%d samples (%.3fs)",
            self._n_freqs, self._freq_min, self._freq_max,
            self._overlap, self._overlap / self._sample_rate,
        )

    def _precompute_kernels(self) -> None:
        self._kernels_fft = [
            _make_morlet_kernel(freq, nc, self._sample_rate, self._n_fft)
            for freq, nc in zip(self._frequencies, self._n_cycles)
        ]

    def process(self, result: ProcessResult) -> ProcessResult:
        chunk = result.chunk
        n_samples = chunk.n_samples

        # Channel selection
        if self._channels is not None:
            ch_mask = np.isin(chunk.channel_ids, self._channels)
            data = chunk.samples[ch_mask]
        else:
            data = chunk.samples

        # Overlap-save: prepend historical samples from ring buffer
        overlap_used = 0
        if result.ring_buffer is not None and self._overlap > 0:
            avail = result.ring_buffer.available
            want = self._overlap + n_samples
            if avail >= want:
                extended = result.ring_buffer.read(want)
                if self._channels is not None:
                    extended = extended[ch_mask]
                data = extended
                overlap_used = self._overlap

        n_conv = data.shape[1]
        n_ch = data.shape[0]
        n_freqs = len(self._frequencies)

        # Recompute kernels if convolution size changed
        needed_fft = next_fast_len(n_conv + self._max_kernel_len - 1)
        if needed_fft != self._n_fft:
            self._n_fft = needed_fft
            self._precompute_kernels()

        # FFT of all channels: (n_ch, n_fft)
        data_fft = fft(data, n=self._n_fft, axis=1)

        # Convolve each frequency band
        analytic = np.zeros((n_ch, n_freqs, n_samples), dtype=np.complex128)
        for fi, kernel_fft in enumerate(self._kernels_fft):
            conv = ifft(data_fft * kernel_fft[np.newaxis, :], axis=1)
            analytic[:, fi, :] = conv[:, overlap_used:overlap_used + n_samples]

        result.wavelet = WaveletResult(
            analytic=analytic, frequencies=self._frequencies, chunk=chunk,
        )
        result.wavelet_settled = (overlap_used > 0)
        return result

    def reset(self) -> None:
        pass  # Stateless — kernels persist
