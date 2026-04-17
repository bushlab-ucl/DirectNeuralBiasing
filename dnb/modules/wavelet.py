"""Wavelet convolution — sliding window from the shared ring buffer.

TWave-style architecture: on each chunk, read a window of recent data
from the shared ring buffer (back context + current chunk), convolve
with the Morlet kernel bank, and extract results for the current chunk
from the output. No internal delay, no settling flag, no forward context.

The causal approach means the wavelet only uses past + current data.
Phase estimates at the trailing edge of the chunk are slightly less
accurate than symmetric overlap-save, but TWave shows this is
clinically sufficient and it eliminates the chunk-duration sensitivity.

The wavelet auto-detects the actual sample rate from the first chunk
(handles upstream downsampler transparently).
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
    """Complex Morlet wavelet kernel in frequency domain (zero-phase)."""
    sigma = n_cycles / (2.0 * np.pi * freq)
    half_len = int(4.0 * sigma * sample_rate)
    t = np.arange(-half_len, half_len + 1) / sample_rate

    wavelet = np.exp(2j * np.pi * freq * t) * np.exp(-(t ** 2) / (2.0 * sigma ** 2))
    wavelet /= np.sqrt(np.sum(np.abs(wavelet) ** 2))

    # Place in FFT buffer (zero-phase: symmetric around t=0)
    kernel = np.zeros(n_fft, dtype=np.complex128)
    kernel[:half_len + 1] = wavelet[half_len:]
    kernel[n_fft - half_len:] = wavelet[:half_len]
    return fft(kernel)


class WaveletConvolution(Module):
    """Single-channel Morlet wavelet decomposition.

    Reads from the shared ring buffer. No internal delay.
    Output: WaveletResult with analytic shape (n_freqs, n_samples).
    """

    def __init__(
        self,
        freq_min: float = 0.5,
        freq_max: float = 30.0,
        n_freqs: int = 10,
        n_cycles_base: float = 3.0,
    ) -> None:
        self._freq_min = freq_min
        self._freq_max = freq_max
        self._n_freqs = n_freqs
        self._n_cycles_base = n_cycles_base

        self._frequencies: NDArray[np.float64] | None = None
        self._n_cycles: NDArray[np.float64] | None = None
        self._kernels_fft: list[NDArray[np.complex128]] = []
        self._n_fft: int = 0
        self._sample_rate: float = 0.0
        self._max_kernel_half_len: int = 0
        self._built: bool = False

    @property
    def frequencies(self) -> NDArray[np.float64]:
        if self._frequencies is None:
            raise RuntimeError("Module not configured yet.")
        return self._frequencies

    @property
    def max_kernel_half_len(self) -> int:
        return self._max_kernel_half_len

    def configure(self, config: PipelineConfig) -> None:
        self._frequencies = np.geomspace(self._freq_min, self._freq_max, self._n_freqs)
        self._n_cycles = self._n_cycles_base * (self._frequencies / self._freq_min)
        self._built = False

    def _build_kernels(self, sample_rate: float, window_len: int) -> None:
        """Build FFT kernels for the convolution window size."""
        self._sample_rate = sample_rate

        max_half = 0
        for freq, nc in zip(self._frequencies, self._n_cycles):
            sigma = nc / (2.0 * np.pi * freq)
            half_len = int(4.0 * sigma * sample_rate)
            max_half = max(max_half, half_len)
        self._max_kernel_half_len = max_half

        self._n_fft = next_fast_len(window_len + 2 * max_half)
        self._kernels_fft = [
            _make_morlet_kernel(freq, nc, sample_rate, self._n_fft)
            for freq, nc in zip(self._frequencies, self._n_cycles)
        ]
        self._built = True

        logger.info(
            "WaveletConvolution: %d freqs (%.1f–%.1f Hz), n_cycles_base=%.1f, "
            "rate=%.0f Hz, kernel_half=%d samples (%.3fs)",
            self._n_freqs, self._freq_min, self._freq_max,
            self._n_cycles_base, sample_rate,
            max_half, max_half / sample_rate,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        chunk = result.chunk
        n_samples = chunk.n_samples
        ring = result.ring_buffer

        # Can't do anything without the ring buffer
        if ring is None:
            result.wavelet = None
            return result

        # Lazy build for actual rate
        if not self._built or abs(chunk.sample_rate - self._sample_rate) > 0.1:
            # Estimate a reasonable window size for kernel building
            # (back context + chunk)
            est_window = n_samples * 10  # generous estimate
            self._build_kernels(chunk.sample_rate, est_window)

        # How much back context do we want?
        back_want = self._max_kernel_half_len
        total_want = back_want + n_samples
        avail = ring.available

        if avail < n_samples:
            # Not even a full chunk in the buffer yet
            result.wavelet = None
            return result

        # Read what we can from the ring buffer
        read_len = min(total_want, avail)
        data = ring.read_latest(read_len)

        # How much back context did we actually get?
        back_actual = read_len - n_samples

        # The chunk's data is the last n_samples of what we read
        # Convolve the full window, extract the chunk portion

        # Rebuild FFT if window size changed
        needed_fft = next_fast_len(read_len + 2 * self._max_kernel_half_len)
        if needed_fft != self._n_fft:
            self._n_fft = needed_fft
            self._kernels_fft = [
                _make_morlet_kernel(freq, nc, self._sample_rate, self._n_fft)
                for freq, nc in zip(self._frequencies, self._n_cycles)
            ]

        data_fft = fft(data, n=self._n_fft)

        n_freqs = len(self._frequencies)
        analytic = np.zeros((n_freqs, n_samples), dtype=np.complex128)
        for fi, kernel_fft in enumerate(self._kernels_fft):
            conv = ifft(data_fft * kernel_fft)
            # Extract the last n_samples (corresponding to current chunk)
            analytic[fi, :] = conv[back_actual:back_actual + n_samples]

        result.wavelet = WaveletResult(
            analytic=analytic, frequencies=self._frequencies, chunk=chunk,
        )
        # Settled = we have enough back context for clean convolution
        result.wavelet_settled = back_actual >= self._max_kernel_half_len
        return result

    def reset(self) -> None:
        self._built = False