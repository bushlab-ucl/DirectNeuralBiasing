"""Wavelet convolution module for time-frequency decomposition.

Complex Morlet wavelets with log-spaced centre frequencies and 1/f
scaling. Single-pass replacement for traditional bandpass filter banks.

Overlap-save strategy (v4 — auto-adapts to actual chunk rate):
    The zero-phase Morlet kernel needs both past AND future context.
    The wavelet manages its own one-chunk delay internally: when it
    receives chunk N, it outputs results for chunk N-1 using chunk N
    as forward context from the ring buffer.

    This version auto-detects the actual sample rate from the first
    chunk it receives (which may differ from PipelineConfig.sample_rate
    if a Downsampler sits upstream). Kernels are built on first process()
    call using the actual rate.

n_cycles_base:
    Controls time-frequency tradeoff. Lower values (1.0–1.5) give
    shorter kernels and faster settling for real-time use.
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

    kernel = np.zeros(n_fft, dtype=np.complex128)
    kernel[:half_len + 1] = wavelet[half_len:]
    kernel[n_fft - half_len:] = wavelet[:half_len]
    return fft(kernel)


class WaveletConvolution(Module):
    """Log-spaced, 1/f-scaled complex Morlet wavelet decomposition.

    Auto-detects actual sample rate from incoming chunks to handle a
    Downsampler sitting upstream.
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
        """Called at pipeline setup. Kernels built lazily on first chunk."""
        self._frequencies = np.geomspace(self._freq_min, self._freq_max, self._n_freqs)
        self._n_cycles = self._n_cycles_base * (self._frequencies / self._freq_min)
        self._prev_chunk = None
        self._configured_for_rate = False

    def _build_kernels_for_rate(self, sample_rate: float, chunk_samples: int) -> None:
        """Build FFT kernels for a specific sample rate and chunk size."""
        self._sample_rate = sample_rate
        self._chunk_samples = chunk_samples

        max_half = 0
        for freq, nc in zip(self._frequencies, self._n_cycles):
            sigma = nc / (2.0 * np.pi * freq)
            half_len = int(4.0 * sigma * sample_rate)
            max_half = max(max_half, half_len)
        self._max_kernel_half_len = max_half

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
            "rate=%.0f Hz, kernel_half=%d samples (%.3fs), chunk=%d samples, "
            "internal delay=1 chunk (%.3fs)",
            self._n_freqs, self._freq_min, self._freq_max,
            self._n_cycles_base, sample_rate,
            self._max_kernel_half_len,
            self._max_kernel_half_len / sample_rate,
            self._chunk_samples,
            self._chunk_samples / sample_rate,
        )

    def process(self, result: ProcessResult) -> ProcessResult:
        chunk = result.chunk

        # Lazy configure for the actual rate on first chunk
        if (not self._configured_for_rate
                or abs(chunk.sample_rate - self._sample_rate) > 0.1
                or chunk.n_samples != self._chunk_samples):
            self._build_kernels_for_rate(chunk.sample_rate, chunk.n_samples)
            self._prev_chunk = None  # reset delay if rate changed

        # --- Internal one-chunk delay ---
        if self._prev_chunk is None:
            self._prev_chunk = chunk
            result.wavelet = None
            result.wavelet_settled = False
            return result

        target_chunk = self._prev_chunk
        self._prev_chunk = chunk
        n_samples = target_chunk.n_samples

        ch_mask = None
        if self._channels is not None:
            ch_mask = np.isin(target_chunk.channel_ids, self._channels)

        fwd_want = min(self._max_kernel_half_len, chunk.n_samples)
        back_want = self._max_kernel_half_len
        total_want = back_want + n_samples + fwd_want

        data = target_chunk.samples
        if ch_mask is not None:
            data = data[ch_mask]
        overlap_back_used = 0
        overlap_fwd_used = 0

        if result.ring_buffer is not None:
            avail = result.ring_buffer.available
            if avail >= total_want:
                extra = chunk.n_samples - fwd_want
                extended = result.ring_buffer.read(total_want + extra)
                if ch_mask is not None:
                    extended = extended[ch_mask]
                if extra > 0:
                    extended = extended[:, :total_want]
                data = extended
                overlap_back_used = back_want
                overlap_fwd_used = fwd_want
            elif avail > n_samples + chunk.n_samples:
                extra = chunk.n_samples - fwd_want
                read_amount = min(avail, total_want + extra)
                extended = result.ring_buffer.read(read_amount)
                if ch_mask is not None:
                    extended = extended[ch_mask]
                if extra > 0 and extended.shape[1] > total_want:
                    extended = extended[:, :total_want]
                actual_total = extended.shape[1]
                overlap_fwd_used = min(fwd_want, actual_total - n_samples)
                if overlap_fwd_used < 0:
                    overlap_fwd_used = 0
                overlap_back_used = actual_total - n_samples - overlap_fwd_used
                if overlap_back_used < 0:
                    overlap_back_used = 0
                data = extended

        n_conv = data.shape[1]
        n_ch = data.shape[0]
        n_freqs = len(self._frequencies)

        needed_fft = next_fast_len(n_conv + 2 * self._max_kernel_half_len)
        if needed_fft != self._n_fft:
            self._n_fft = needed_fft
            self._kernels_fft = [
                _make_morlet_kernel(freq, nc, self._sample_rate, self._n_fft)
                for freq, nc in zip(self._frequencies, self._n_cycles)
            ]

        data_fft = fft(data, n=self._n_fft, axis=1)

        analytic = np.zeros((n_ch, n_freqs, n_samples), dtype=np.complex128)
        for fi, kernel_fft in enumerate(self._kernels_fft):
            conv = ifft(data_fft * kernel_fft[np.newaxis, :], axis=1)
            analytic[:, fi, :] = conv[:, overlap_back_used:overlap_back_used + n_samples]

        result.chunk = target_chunk
        result.wavelet = WaveletResult(
            analytic=analytic, frequencies=self._frequencies, chunk=target_chunk,
        )
        result.wavelet_settled = (
            overlap_back_used >= self._max_kernel_half_len
            and overlap_fwd_used > 0
        )
        return result

    def flush(self, result: ProcessResult) -> ProcessResult:
        """Process the final stashed chunk at end-of-stream."""
        if self._prev_chunk is None:
            return result

        target_chunk = self._prev_chunk
        self._prev_chunk = None
        n_samples = target_chunk.n_samples

        ch_mask = None
        if self._channels is not None:
            ch_mask = np.isin(target_chunk.channel_ids, self._channels)

        data = target_chunk.samples
        if ch_mask is not None:
            data = data[ch_mask]
        overlap_back_used = 0

        if result.ring_buffer is not None:
            back_want = self._max_kernel_half_len
            total_want = back_want + n_samples
            avail = result.ring_buffer.available
            if avail >= total_want:
                extended = result.ring_buffer.read(total_want)
                if ch_mask is not None:
                    extended = extended[ch_mask]
                data = extended
                overlap_back_used = back_want

        n_conv = data.shape[1]
        n_ch = data.shape[0]
        n_freqs = len(self._frequencies)

        needed_fft = next_fast_len(n_conv + 2 * self._max_kernel_half_len)
        if needed_fft != self._n_fft:
            self._n_fft = needed_fft
            self._kernels_fft = [
                _make_morlet_kernel(freq, nc, self._sample_rate, self._n_fft)
                for freq, nc in zip(self._frequencies, self._n_cycles)
            ]

        data_fft = fft(data, n=self._n_fft, axis=1)
        analytic = np.zeros((n_ch, n_freqs, n_samples), dtype=np.complex128)
        for fi, kernel_fft in enumerate(self._kernels_fft):
            conv = ifft(data_fft * kernel_fft[np.newaxis, :], axis=1)
            analytic[:, fi, :] = conv[:, overlap_back_used:overlap_back_used + n_samples]

        result.chunk = target_chunk
        result.wavelet = WaveletResult(
            analytic=analytic, frequencies=self._frequencies, chunk=target_chunk,
        )
        result.wavelet_settled = False
        return result

    def reset(self) -> None:
        self._prev_chunk = None