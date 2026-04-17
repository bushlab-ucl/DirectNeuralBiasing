"""Wavelet convolution — single channel, symmetric overlap-save.

Complex Morlet wavelets with log-spaced centre frequencies and 1/f
scaling. Single-pass replacement for bandpass filter banks.

Overlap-save: the wavelet maintains an internal one-chunk delay.
When chunk N arrives, it outputs results for chunk N-1, using
data from the ring buffer for symmetric context. This adds
chunk_duration of latency but eliminates edge artifacts.

Auto-rate-detection: kernels are built from the first chunk's
actual sample rate (post-downsampler if present).
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

    kernel = np.zeros(n_fft, dtype=np.complex128)
    kernel[:half_len + 1] = wavelet[half_len:]
    kernel[n_fft - half_len:] = wavelet[:half_len]
    return fft(kernel)


class WaveletConvolution(Module):
    """Single-channel Morlet wavelet decomposition.

    Output analytic signal has shape (n_freqs, n_samples).
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
        self._chunk_samples: int = 0
        self._configured_for_rate: bool = False

        self._prev_chunk: DataChunk | None = None

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
        self._prev_chunk = None
        self._configured_for_rate = False

    def _build_kernels(self, sample_rate: float, chunk_samples: int) -> None:
        """Build FFT kernels for a specific sample rate and chunk size."""
        self._sample_rate = sample_rate
        self._chunk_samples = chunk_samples

        max_half = 0
        for freq, nc in zip(self._frequencies, self._n_cycles):
            sigma = nc / (2.0 * np.pi * freq)
            half_len = int(4.0 * sigma * sample_rate)
            max_half = max(max_half, half_len)
        self._max_kernel_half_len = max_half

        # Need: back_context + chunk + fwd_context
        fwd = min(max_half, chunk_samples)
        total_input = max_half + chunk_samples + fwd
        self._n_fft = next_fast_len(total_input + 2 * max_half)
        self._kernels_fft = [
            _make_morlet_kernel(freq, nc, sample_rate, self._n_fft)
            for freq, nc in zip(self._frequencies, self._n_cycles)
        ]
        self._configured_for_rate = True

        logger.info(
            "WaveletConvolution: %d freqs (%.1f–%.1f Hz), n_cycles_base=%.1f, "
            "rate=%.0f Hz, kernel_half=%d samples (%.3fs), chunk=%d samples",
            self._n_freqs, self._freq_min, self._freq_max,
            self._n_cycles_base, sample_rate,
            max_half, max_half / sample_rate, chunk_samples,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        chunk = result.chunk

        # Lazy build for actual rate
        if (not self._configured_for_rate
                or abs(chunk.sample_rate - self._sample_rate) > 0.1
                or chunk.n_samples != self._chunk_samples):
            self._build_kernels(chunk.sample_rate, chunk.n_samples)
            self._prev_chunk = None

        # --- One-chunk delay ---
        # First chunk: stash it, output nothing
        if self._prev_chunk is None:
            self._prev_chunk = chunk
            result.wavelet = None
            result.wavelet_settled = False
            return result

        # We output results for prev_chunk, using current chunk as forward context
        target_chunk = self._prev_chunk
        self._prev_chunk = chunk
        n_samples = target_chunk.n_samples

        # Build the extended data array from the ring buffer
        # We want: [back_context | target_chunk | fwd_context]
        back_want = self._max_kernel_half_len
        fwd_want = min(self._max_kernel_half_len, chunk.n_samples)
        total_want = back_want + n_samples + fwd_want

        overlap_back = 0
        overlap_fwd = 0

        if result.ring_buffer is not None:
            avail = result.ring_buffer.available
            # The ring buffer contains all data including current chunk.
            # Most recent = current chunk (fwd context) + target chunk + back context
            read_want = total_want
            if avail >= read_want:
                # Read total_want from the ring buffer. The most recent fwd_want
                # samples are from the current chunk, the next n_samples are target,
                # and the rest is back context.
                extended = result.ring_buffer.read(read_want)
                overlap_back = back_want
                overlap_fwd = fwd_want
                data = extended
            elif avail > n_samples:
                # Partial context
                extended = result.ring_buffer.read(avail)
                actual_total = extended.shape[0]
                # Current chunk is the most recent chunk.n_samples in the buffer
                overlap_fwd = min(fwd_want, max(0, actual_total - n_samples))
                overlap_back = max(0, actual_total - n_samples - overlap_fwd)
                data = extended
            else:
                data = target_chunk.samples
        else:
            data = target_chunk.samples

        # Convolve
        n_conv = data.shape[0]
        n_freqs = len(self._frequencies)

        needed_fft = next_fast_len(n_conv + 2 * self._max_kernel_half_len)
        if needed_fft != self._n_fft:
            self._n_fft = needed_fft
            self._kernels_fft = [
                _make_morlet_kernel(freq, nc, self._sample_rate, self._n_fft)
                for freq, nc in zip(self._frequencies, self._n_cycles)
            ]

        data_fft = fft(data, n=self._n_fft)

        analytic = np.zeros((n_freqs, n_samples), dtype=np.complex128)
        for fi, kernel_fft in enumerate(self._kernels_fft):
            conv = ifft(data_fft * kernel_fft)
            analytic[fi, :] = conv[overlap_back:overlap_back + n_samples]

        result.chunk = target_chunk
        result.wavelet = WaveletResult(
            analytic=analytic, frequencies=self._frequencies, chunk=target_chunk,
        )
        result.wavelet_settled = (
            overlap_back >= self._max_kernel_half_len
            and overlap_fwd > 0
        )
        return result

    def flush(self, result: ProcessResult) -> ProcessResult:
        """Process the final stashed chunk at end-of-stream (no forward context)."""
        if self._prev_chunk is None:
            return result

        target_chunk = self._prev_chunk
        self._prev_chunk = None
        n_samples = target_chunk.n_samples

        data = target_chunk.samples
        overlap_back = 0

        if result.ring_buffer is not None:
            back_want = self._max_kernel_half_len
            total_want = back_want + n_samples
            avail = result.ring_buffer.available
            if avail >= total_want:
                extended = result.ring_buffer.read(total_want)
                data = extended
                overlap_back = back_want

        n_conv = data.shape[0]
        n_freqs = len(self._frequencies)

        needed_fft = next_fast_len(n_conv + 2 * self._max_kernel_half_len)
        if needed_fft != self._n_fft:
            self._n_fft = needed_fft
            self._kernels_fft = [
                _make_morlet_kernel(freq, nc, self._sample_rate, self._n_fft)
                for freq, nc in zip(self._frequencies, self._n_cycles)
            ]

        data_fft = fft(data, n=self._n_fft)
        analytic = np.zeros((n_freqs, n_samples), dtype=np.complex128)
        for fi, kernel_fft in enumerate(self._kernels_fft):
            conv = ifft(data_fft * kernel_fft)
            analytic[fi, :] = conv[overlap_back:overlap_back + n_samples]

        result.chunk = target_chunk
        result.wavelet = WaveletResult(
            analytic=analytic, frequencies=self._frequencies, chunk=target_chunk,
        )
        result.wavelet_settled = False  # no forward context
        return result

    def reset(self) -> None:
        self._prev_chunk = None