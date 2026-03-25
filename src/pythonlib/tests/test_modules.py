"""Tests for wavelet convolution and downstream modules."""

import numpy as np
import pytest

from dnb.core.types import DataChunk, EventType, PipelineConfig, WaveletResult
from dnb.modules.base import ProcessResult
from dnb.modules.detector import EventDetector
from dnb.modules.power import PowerEstimator
from dnb.modules.wavelet import WaveletConvolution


def _make_chunk(
    n_channels: int = 4,
    n_samples: int = 6000,
    sample_rate: float = 30000.0,
    freq: float | None = None,
) -> DataChunk:
    """Create a test DataChunk, optionally with a pure sine wave."""
    t = np.arange(n_samples) / sample_rate
    if freq is not None:
        samples = np.sin(2 * np.pi * freq * t)[np.newaxis, :].repeat(n_channels, axis=0)
    else:
        rng = np.random.default_rng(42)
        samples = rng.standard_normal((n_channels, n_samples))

    return DataChunk(
        samples=samples,
        timestamps=t,
        channel_ids=np.arange(n_channels, dtype=np.int32),
        sample_rate=sample_rate,
    )


class TestWaveletConvolution:
    def test_output_shape(self):
        config = PipelineConfig(sample_rate=30000, n_channels=4, chunk_duration=0.2)
        wc = WaveletConvolution(freq_min=2, freq_max=200, n_freqs=20)
        wc.configure(config)

        chunk = _make_chunk(n_channels=4, n_samples=6000)
        result = wc.process(ProcessResult(chunk=chunk))

        assert result.wavelet is not None
        assert result.wavelet.analytic.shape == (4, 20, 6000)
        assert result.wavelet.frequencies.shape == (20,)

    def test_frequencies_are_log_spaced(self):
        wc = WaveletConvolution(freq_min=1, freq_max=100, n_freqs=10)
        config = PipelineConfig(sample_rate=30000, n_channels=1)
        wc.configure(config)

        freqs = wc.frequencies
        log_freqs = np.log(freqs)
        diffs = np.diff(log_freqs)
        # Log-spaced means equal spacing in log domain
        np.testing.assert_allclose(diffs, diffs[0], rtol=1e-10)

    def test_peak_at_signal_frequency(self):
        """A pure 100 Hz sine should produce peak amplitude near 100 Hz."""
        config = PipelineConfig(sample_rate=30000, n_channels=1, chunk_duration=0.5)
        wc = WaveletConvolution(freq_min=10, freq_max=300, n_freqs=30)
        wc.configure(config)

        chunk = _make_chunk(n_channels=1, n_samples=15000, freq=100.0)
        result = wc.process(ProcessResult(chunk=chunk))
        wavelet = result.wavelet

        # Mean amplitude per frequency band (skip edges for edge effects)
        mean_amp = np.mean(wavelet.amplitude[0, :, 2000:-2000], axis=1)
        peak_freq = wavelet.frequencies[np.argmax(mean_amp)]

        # Peak should be within 20% of 100 Hz
        assert abs(peak_freq - 100.0) / 100.0 < 0.2, f"Peak at {peak_freq:.1f} Hz"

    def test_amplitude_and_phase_properties(self):
        config = PipelineConfig(sample_rate=30000, n_channels=1)
        wc = WaveletConvolution(n_freqs=5)
        wc.configure(config)

        chunk = _make_chunk(n_channels=1, n_samples=6000)
        result = wc.process(ProcessResult(chunk=chunk))
        w = result.wavelet

        # Amplitude should be non-negative
        assert np.all(w.amplitude >= 0)

        # Phase should be in [-pi, pi]
        assert np.all(w.phase >= -np.pi)
        assert np.all(w.phase <= np.pi)

        # Power = amplitude^2
        np.testing.assert_allclose(w.power, w.amplitude**2)

    def test_channel_selection(self):
        config = PipelineConfig(sample_rate=30000, n_channels=8)
        wc = WaveletConvolution(n_freqs=5, channels=[2, 5])
        wc.configure(config)

        chunk = _make_chunk(n_channels=8, n_samples=6000)
        result = wc.process(ProcessResult(chunk=chunk))

        # Should only process 2 channels
        assert result.wavelet.analytic.shape[0] == 2


class TestPowerEstimator:
    def test_band_power_keys(self):
        config = PipelineConfig(sample_rate=30000, n_channels=2)
        wc = WaveletConvolution(freq_min=1, freq_max=200, n_freqs=30)
        pe = PowerEstimator()
        wc.configure(config)
        pe.configure(config)

        chunk = _make_chunk(n_channels=2, n_samples=6000)
        result = wc.process(ProcessResult(chunk=chunk))
        result = pe.process(result)

        expected_bands = ["delta", "theta", "alpha", "beta", "low_gamma", "high_gamma"]
        for band in expected_bands:
            assert f"power_{band}" in result.data
            assert f"power_{band}_mean" in result.data

    def test_custom_bands(self):
        config = PipelineConfig(sample_rate=30000, n_channels=1)
        wc = WaveletConvolution(freq_min=1, freq_max=200, n_freqs=30)
        pe = PowerEstimator(bands={"ripple": (80, 200)})
        wc.configure(config)
        pe.configure(config)

        chunk = _make_chunk(n_channels=1, n_samples=6000)
        result = wc.process(ProcessResult(chunk=chunk))
        result = pe.process(result)

        assert "power_ripple" in result.data
        assert "power_delta" not in result.data


class TestEventDetector:
    def test_detects_high_amplitude_burst(self):
        """Inject a loud burst and check that the detector finds it."""
        config = PipelineConfig(sample_rate=1000, n_channels=1, chunk_duration=2.0)
        wc = WaveletConvolution(freq_min=50, freq_max=200, n_freqs=10, n_cycles_base=3)
        det = EventDetector(
            event_type=EventType.RIPPLE,
            freq_range=(80, 200),
            threshold_std=2.0,
            min_duration=0.01,
            cooldown=0.05,
        )
        wc.configure(config)
        det.configure(config)

        # Build signal: noise + loud 120Hz burst in the middle
        rng = np.random.default_rng(123)
        n_samples = 2000
        t = np.arange(n_samples) / 1000.0
        signal = rng.standard_normal((1, n_samples)) * 0.1

        # Inject burst from 0.8s to 1.2s
        burst_start = 800
        burst_end = 1200
        signal[0, burst_start:burst_end] += 5.0 * np.sin(
            2 * np.pi * 120 * t[burst_start:burst_end]
        )

        chunk = DataChunk(
            samples=signal,
            timestamps=t,
            channel_ids=np.array([0], dtype=np.int32),
            sample_rate=1000.0,
        )

        # First chunk to establish baseline
        baseline_chunk = DataChunk(
            samples=rng.standard_normal((1, n_samples)) * 0.1,
            timestamps=t,
            channel_ids=np.array([0], dtype=np.int32),
            sample_rate=1000.0,
        )
        r0 = wc.process(ProcessResult(chunk=baseline_chunk))
        det.process(r0)

        # Now the chunk with the burst
        result = wc.process(ProcessResult(chunk=chunk))
        result = det.process(result)

        assert len(result.events) > 0, "Should detect at least one event"
        evt = result.events[0]
        assert evt.event_type == EventType.RIPPLE
        # Event should be roughly in the burst window
        assert 0.5 < evt.timestamp < 1.5
