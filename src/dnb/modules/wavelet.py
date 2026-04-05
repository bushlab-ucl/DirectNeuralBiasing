"""Wavelet convolution module for time-frequency decomposition.

Uses complex Morlet wavelets with log-spaced centre frequencies and
1/f scaling (longer wavelets at lower frequencies) to extract
instantaneous amplitude and phase across all bands in a single pass.

This replaces traditional bandpass filter banks: instead of N separate
IIR filters you get a single convolution that yields the analytic signal
at every (channel, frequency, time) point.

Design choices:
    - Log-spaced frequencies match the 1/f spectral structure of neural signals.
    - 1/f scaling: n_cycles grows with frequency (constant fractional bandwidth),
      so low-frequency wavelets are long (good frequency resolution) and
      high-frequency wavelets are short (good time resolution).
    - FFT-based convolution for efficiency on long chunks.
    - Kernels are pre-computed once in configure().
    - Overlap-save: when a ring buffer is available, the module reads
      extra historical samples so that chunk-boundary edge artefacts
      are confined to the discarded prefix.
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
    freq: float,
    n_cycles: float,
    sample_rate: float,
    n_fft: int,
) -> NDArray[np.complex128]:
    """Create a complex Morlet wavelet kernel in the frequency domain.

    The wavelet is defined in the time domain as:
        w(t) = exp(2πi·f·t) · exp(-t² / (2σ²))
    where σ = n_cycles / (2πf), giving n_cycles oscillations within
    the Gaussian envelope.

    We compute the FFT of this kernel for convolution in the frequency domain.

    Args:
        freq: Centre frequency in Hz.
        n_cycles: Number of cycles in the Gaussian envelope.
        sample_rate: Sampling rate in Hz.
        n_fft: FFT length for the convolution.

    Returns:
        Complex frequency-domain kernel, shape (n_fft,).
    """
    sigma = n_cycles / (2.0 * np.pi * freq)

    # Time vector: enough to capture the wavelet (±4σ)
    half_len = int(4.0 * sigma * sample_rate)
    t = np.arange(-half_len, half_len + 1) / sample_rate

    # Complex Morlet in time domain
    wavelet = np.exp(2j * np.pi * freq * t) * np.exp(-(t**2) / (2.0 * sigma**2))

    # Normalise to unit energy
    wavelet /= np.sqrt(np.sum(np.abs(wavelet) ** 2))

    # FFT at the given length (caller ensures n_fft >= len(wavelet))
    return fft(wavelet, n=n_fft)


class WaveletConvolution(Module):
    """Log-spaced, 1/f-scaled complex Morlet wavelet decomposition.

    Produces a WaveletResult containing the full analytic signal at each
    (channel, frequency, time) point. Downstream modules can read
    .amplitude, .phase, or .power directly.

    When a ring buffer is available in the ProcessResult, the module
    automatically prepends historical samples (overlap-save) so that
    edge artefacts from the FFT convolution fall in the discarded
    prefix rather than corrupting the output.

    Args:
        freq_min: Lowest centre frequency in Hz.
        freq_max: Highest centre frequency in Hz.
        n_freqs: Number of log-spaced frequency bins.
        n_cycles_base: Number of cycles at freq_min. Scales linearly
            with frequency (1/f scaling), so higher frequencies get
            proportionally more cycles (tighter temporal resolution
            relative to their period, same fractional bandwidth).
        channels: Which channels to decompose. None = all channels.
    """

    def __init__(
        self,
        freq_min: float = 1.0,
        freq_max: float = 200.0,
        n_freqs: int = 40,
        n_cycles_base: float = 3.0,
        channels: list[int] | None = None,
    ) -> None:
        self._freq_min = freq_min
        self._freq_max = freq_max
        self._n_freqs = n_freqs
        self._n_cycles_base = n_cycles_base
        self._channels = channels

        # Computed during configure()
        self._frequencies: NDArray[np.float64] | None = None
        self._n_cycles: NDArray[np.float64] | None = None
        self._kernels_fft: list[NDArray[np.complex128]] = []
        self._n_fft: int = 0
        self._sample_rate: float = 0.0
        self._max_kernel_len: int = 0
        # Overlap length: number of prefix samples needed to absorb edge effects
        self._overlap: int = 0

    @property
    def frequencies(self) -> NDArray[np.float64]:
        """Centre frequencies of the wavelet bank."""
        if self._frequencies is None:
            raise RuntimeError("Module not configured yet.")
        return self._frequencies

    def configure(self, config: PipelineConfig) -> None:
        self._sample_rate = config.sample_rate

        # Log-spaced centre frequencies
        self._frequencies = np.geomspace(
            self._freq_min, self._freq_max, self._n_freqs
        )

        # 1/f scaling: n_cycles proportional to frequency
        # At freq_min we use n_cycles_base; at higher freqs, more cycles
        self._n_cycles = self._n_cycles_base * (self._frequencies / self._freq_min)

        # Compute the longest kernel length (lowest frequency has widest Gaussian)
        max_kernel_len = 0
        for freq, nc in zip(self._frequencies, self._n_cycles):
            sigma = nc / (2.0 * np.pi * freq)
            half_len = int(4.0 * sigma * self._sample_rate)
            kernel_len = 2 * half_len + 1
            max_kernel_len = max(max_kernel_len, kernel_len)
        self._max_kernel_len = max_kernel_len

        # The overlap needed is kernel_len - 1 (standard overlap-save).
        self._overlap = max_kernel_len - 1

        # FFT length must fit both the data and the longest kernel
        # for correct linear convolution
        self._n_fft = next_fast_len(config.chunk_samples + max_kernel_len - 1)
        self._precompute_kernels()

        logger.info(
            "WaveletConvolution configured: %d freqs (%.1f–%.1f Hz), "
            "overlap=%d samples (%.3fs)",
            self._n_freqs,
            self._freq_min,
            self._freq_max,
            self._overlap,
            self._overlap / self._sample_rate,
        )

    def _precompute_kernels(self) -> None:
        """Build frequency-domain wavelet kernels for all bands."""
        self._kernels_fft = []
        for freq, nc in zip(self._frequencies, self._n_cycles):
            kernel = _make_morlet_kernel(freq, nc, self._sample_rate, self._n_fft)
            self._kernels_fft.append(kernel)

    def process(self, result: ProcessResult) -> ProcessResult:
        chunk = result.chunk
        n_samples = chunk.n_samples

        # --- Channel selection ---
        if self._channels is not None:
            ch_mask = np.isin(chunk.channel_ids, self._channels)
            data = chunk.samples[ch_mask]
            ch_ids = chunk.channel_ids[ch_mask]
        else:
            data = chunk.samples
            ch_ids = chunk.channel_ids

        # --- Overlap-save: prepend exactly self._overlap historical samples ---
        # This eliminates edge artefacts at chunk boundaries.  We read
        # (overlap + n_samples) from the ring buffer, which already contains
        # the current chunk.  Only the last n_samples of the convolution
        # output are kept — the prefix absorbs the transient.
        #
        # Important: we always request exactly self._overlap samples of
        # history (not more, not less) so the convolution length and FFT
        # size stay constant across chunks.
        #
        # Note: when a Downsampler is in the chain, result.ring_buffer
        # has been swapped to the Downsampler's internal buffer (at the
        # downsampled rate), so the overlap data is at the correct rate.
        overlap_used = 0
        if result.ring_buffer is not None and self._overlap > 0:
            avail = result.ring_buffer.available
            want = self._overlap + n_samples
            if avail >= want:
                # Full overlap available — normal case after buffer fills
                extended = result.ring_buffer.read(want)
                if self._channels is not None:
                    extended = extended[ch_mask]
                data = extended
                overlap_used = self._overlap
            # If not enough history yet, just process the chunk as-is
            # (edge artefacts on early chunks, but consistent amplitude)

        n_conv = data.shape[1]
        n_ch = data.shape[0]
        n_freqs = len(self._frequencies)

        # Recompute kernels if convolution size changed
        needed_fft = next_fast_len(n_conv + self._max_kernel_len - 1)
        if needed_fft != self._n_fft:
            logger.debug(
                "Wavelet FFT size changed: %d → %d (chunk had %d samples)",
                self._n_fft, needed_fft, n_conv,
            )
            self._n_fft = needed_fft
            self._precompute_kernels()

        # FFT of all channels at once: (n_ch, n_fft)
        data_fft = fft(data, n=self._n_fft, axis=1)

        # Convolve each frequency band
        analytic = np.zeros((n_ch, n_freqs, n_samples), dtype=np.complex128)
        for fi, kernel_fft in enumerate(self._kernels_fft):
            # Multiply in frequency domain, IFFT back
            conv = ifft(data_fft * kernel_fft[np.newaxis, :], axis=1)
            # Discard the overlap prefix — keep only the last n_samples
            analytic[:, fi, :] = conv[:, overlap_used : overlap_used + n_samples]

        wavelet_result = WaveletResult(
            analytic=analytic,
            frequencies=self._frequencies,
            chunk=chunk,
        )

        result.wavelet = wavelet_result
        return result

    def reset(self) -> None:
        pass  # Stateless — kernels persist across resets
