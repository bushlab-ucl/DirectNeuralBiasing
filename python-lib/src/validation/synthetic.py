"""Synthetic data generation for validation.

Generates neural-like signals with known, planted events so that
detector accuracy can be measured against ground truth.
"""

from __future__ import annotations

# TODO: Implement synthetic data generation
#
# Plan:
#   - generate_pink_noise(n_channels, n_samples, sample_rate) -> NDArray
#       1/f background matching real neural spectral profile
#
#   - inject_oscillatory_burst(signal, channel, time, freq, duration, amplitude)
#       Plant a known-frequency burst (e.g. synthetic ripple at 120 Hz)
#       Returns the modified signal and a ground-truth Event
#
#   - generate_synthetic_recording(
#         n_channels=83, duration=60.0, sample_rate=30000,
#         n_ripples=50, n_spindles=20, snr=3.0
#     ) -> (NDArray, list[Event])
#       Full synthetic recording with planted events and ground truth labels
#
#   - save_synthetic(path, data, events, sample_rate)
#       Save in DNB .npz format compatible with FileSource
