"""Synthetic data generation — single channel, 1D signals."""

from __future__ import annotations

import logging
from math import pi
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from dnb.core.types import Event, EventType

logger = logging.getLogger(__name__)


def generate_pink_noise(
    n_samples: int, sample_rate: float, seed: int = 42,
) -> NDArray[np.float64]:
    """Generate 1/f (pink) noise — 1D."""
    n_samples = int(n_samples)  # ensure integer
    rng = np.random.default_rng(seed)
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate)
    freqs[0] = 1.0

    white = rng.standard_normal(n_samples)
    white_fft = np.fft.rfft(white)
    pink_fft = white_fft / np.sqrt(freqs)
    noise = np.fft.irfft(pink_fft, n=n_samples)
    noise /= np.std(noise)
    return noise


def inject_slow_wave(
    signal: NDArray[np.float64],
    time_s: float,
    sample_rate: float,
    frequency: float = 1.0,
    amplitude: float = 500.0,
    n_cycles: int = 2,
    channel_id: int = 0,
) -> Event:
    """Plant a known slow wave (Hann-windowed sinusoid)."""
    duration = n_cycles / frequency
    half_dur = duration / 2.0
    start_idx = max(0, int((time_s - half_dur) * sample_rate))
    end_idx = min(signal.shape[0], int((time_s + half_dur) * sample_rate))
    n = end_idx - start_idx

    if n > 0:
        t = np.arange(n) / sample_rate
        window = np.hanning(n)
        sw = amplitude * np.sin(2 * pi * frequency * t) * window
        signal[start_idx:end_idx] += sw

    return Event(
        event_type=EventType.SLOW_WAVE, timestamp=time_s,
        channel_id=channel_id, duration=duration,
        metadata={"synthetic": True, "type": "SW", "amplitude": amplitude, "frequency": frequency},
    )


def inject_ied(
    signal: NDArray[np.float64],
    time_s: float,
    sample_rate: float,
    amplitude: float = 2000.0,
    duration_ms: float = 500.0,
    channel_id: int = 0,
    seed: int | None = None,
) -> Event:
    """Plant a synthetic IED (spike-and-wave complex)."""
    rng = np.random.default_rng(seed)
    dur_s = duration_ms / 1000.0

    start_idx = max(0, int((time_s - dur_s * 0.2) * sample_rate))
    end_idx = min(signal.shape[0], int((time_s + dur_s * 0.8) * sample_rate))
    n = end_idx - start_idx

    if n > 0:
        t = np.arange(n) / sample_rate
        t_spike = dur_s * 0.2
        wave_delay = rng.uniform(0.06, 0.10)
        t_wave = t_spike + wave_delay

        ied = np.zeros(n)
        for f, s, w in [(15.0, 0.015, 0.50), (30.0, 0.008, 0.30), (60.0, 0.004, 0.20)]:
            env = np.exp(-((t - t_spike) ** 2) / (2 * s ** 2))
            ied -= w * env * np.cos(2 * pi * f * (t - t_spike))

        wave_f = rng.uniform(2.5, 4.0)
        wave_env = np.exp(-((t - t_wave) ** 2) / (2 * 0.08 ** 2))
        ied += 0.8 * wave_env * np.cos(2 * pi * wave_f * (t - t_wave))

        ptp = np.max(ied) - np.min(ied)
        if ptp > 0:
            ied *= amplitude / ptp

        signal[start_idx:end_idx] += ied

    return Event(
        event_type=EventType.IED, timestamp=time_s,
        channel_id=channel_id, duration=dur_s,
        metadata={"synthetic": True, "type": "IED", "amplitude": amplitude},
    )


def generate_synthetic_recording(
    duration_s: float = 120.0,
    sample_rate: float = 1000.0,
    n_slow_waves: int = 15,
    n_ieds: int = 5,
    snr: float = 5.0,
    sw_amplitude: float = 500.0,
    sw_frequency: float = 1.0,
    ied_amplitude: float = 5000.0,
    channel_id: int = 0,
    seed: int = 42,
) -> tuple[NDArray[np.float64], list[Event], float]:
    """Generate a synthetic recording. Returns (signal_1d, gt_events, actual_snr)."""
    rng = np.random.default_rng(seed)
    n_samples = int(duration_s * sample_rate)

    noise = generate_pink_noise(n_samples, sample_rate, seed)
    noise_std = np.std(noise)
    noise_scale = sw_amplitude / (snr * noise_std) if snr > 0 else 0.0
    signal = noise * noise_scale

    events: list[Event] = []
    min_spacing = 4.0
    margin = 3.0

    sw_times = _place_events(rng, n_slow_waves, margin, duration_s - margin, min_spacing)
    for t in sw_times:
        events.append(inject_slow_wave(signal, t, sample_rate, sw_frequency, sw_amplitude, channel_id=channel_id))

    ied_times = _place_events(rng, n_ieds, margin, duration_s - margin, min_spacing,
                              avoid=sw_times, avoid_radius=2.0)
    for t in ied_times:
        events.append(inject_ied(signal, t, sample_rate, ied_amplitude, channel_id=channel_id))

    events.sort(key=lambda e: e.timestamp)
    actual_snr = sw_amplitude / (noise_scale * noise_std) if noise_scale > 0 else float("inf")
    return signal, events, actual_snr


def _place_events(
    rng, n: int, lo: float, hi: float, min_spacing: float,
    avoid: list[float] | None = None, avoid_radius: float = 0.0,
) -> list[float]:
    times = []
    for _ in range(n * 100):
        if len(times) >= n:
            break
        t = rng.uniform(lo, hi)
        if all(abs(t - existing) > min_spacing for existing in times):
            if avoid is None or all(abs(t - a) > avoid_radius for a in avoid):
                times.append(t)
    times.sort()
    return times


def save_synthetic(
    path: str | Path,
    signal: NDArray[np.float64],
    sample_rate: float,
    events: list[Event] | None = None,
) -> Path:
    """Save in DNB .npz format. Signal stored as (1, n_samples)."""
    path = Path(path)
    save_signal = signal.reshape(1, -1) if signal.ndim == 1 else signal
    save_dict: dict = {"continuous": save_signal, "sample_rate": np.float64(sample_rate)}
    if events:
        save_dict["gt_timestamps"] = np.array([e.timestamp for e in events])
        save_dict["gt_types"] = np.array([e.metadata.get("type", "unknown") for e in events])
    np.savez(str(path), **save_dict)
    return path