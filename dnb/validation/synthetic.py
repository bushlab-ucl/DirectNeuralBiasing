"""Synthetic data generation for offline validation.

Generates neural-like signals with 1/f (pink) noise backgrounds and
planted slow waves and IEDs at configurable signal-to-noise ratios.

Usage:
    from dnb.validation.synthetic import generate_synthetic_recording, save_synthetic

    signal, gt_events, snr = generate_synthetic_recording(snr=5.0)
    path = save_synthetic("/tmp/test.npz", signal, 1000.0, gt_events)
"""

from __future__ import annotations

import logging
from math import pi
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from dnb.core.types import Event, EventType

logger = logging.getLogger(__name__)


def generate_pink_noise(
    n_channels: int, n_samples: int, sample_rate: float, seed: int = 42,
) -> NDArray[np.float64]:
    """Generate 1/f (pink) noise matching neural spectral profile."""
    rng = np.random.default_rng(seed)
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate)
    freqs[0] = 1.0  # avoid div by zero

    noise = np.zeros((n_channels, n_samples))
    for ch in range(n_channels):
        white = rng.standard_normal(n_samples)
        white_fft = np.fft.rfft(white)
        pink_fft = white_fft / np.sqrt(freqs)
        noise[ch] = np.fft.irfft(pink_fft, n=n_samples)

    noise /= np.std(noise)
    return noise


def inject_slow_wave(
    signal: NDArray[np.float64],
    channel: int,
    time_s: float,
    sample_rate: float,
    frequency: float = 1.0,
    amplitude: float = 500.0,
    n_cycles: int = 2,
) -> Event:
    """Plant a known slow wave (Hann-windowed sinusoid) at a specific time."""
    duration = n_cycles / frequency
    half_dur = duration / 2.0
    start_idx = max(0, int((time_s - half_dur) * sample_rate))
    end_idx = min(signal.shape[1], int((time_s + half_dur) * sample_rate))
    n = end_idx - start_idx

    if n > 0:
        t = np.arange(n) / sample_rate
        window = np.hanning(n)
        sw = amplitude * np.sin(2 * pi * frequency * t) * window
        signal[channel, start_idx:end_idx] += sw

    return Event(
        event_type=EventType.SLOW_WAVE, timestamp=time_s,
        channel_id=channel, duration=duration,
        metadata={"synthetic": True, "type": "SW", "amplitude": amplitude, "frequency": frequency},
    )


def inject_ied(
    signal: NDArray[np.float64],
    channel: int,
    time_s: float,
    sample_rate: float,
    amplitude: float = 2000.0,
    duration_ms: float = 500.0,
    seed: int | None = None,
) -> Event:
    """Plant a synthetic IED as a broadband transient.

    Superposes Gabor atoms at 5–70 Hz, each with an envelope width
    matched to its frequency.  Low-freq atoms give the event its
    ~400 ms temporal footprint; high-freq atoms sharpen the peak.
    """
    rng = np.random.default_rng(seed)
    dur_s = duration_ms / 1000.0

    start_idx = max(0, int((time_s - dur_s * 0.3) * sample_rate))
    end_idx = min(signal.shape[1], int((time_s + dur_s * 0.7) * sample_rate))
    n = end_idx - start_idx

    if n > 0:
        t = np.arange(n) / sample_rate
        t_peak = dur_s * 0.3

        #              freq    sigma    weight
        atoms = [
            (  3.0,   0.120,   0.70),   # dominant — broad deflection
            (  8.0,   0.055,   0.50),   # theta body
            ( 18.0,   0.025,   0.30),   # sharpens the peak
            ( 40.0,   0.012,   0.15),   # adds edge
            ( 70.0,   0.005,   0.05),   # subtle crispness
        ]

        ied = np.zeros(n)
        for f, s, w in atoms:
            f_j = f * (1.0 + (rng.random() - 0.5) * 0.25)
            s_j = s * (1.0 + (rng.random() - 0.5) * 0.20)
            ph  = rng.uniform(-0.3, 0.3)
            env = np.exp(-((t - t_peak) ** 2) / (2 * s_j ** 2))
            ied += w * env * np.cos(2 * pi * f_j * (t - t_peak) + ph)

        # Scale to peak-to-peak amplitude
        ptp = np.max(ied) - np.min(ied)
        if ptp > 0:
            ied *= amplitude / ptp
        signal[channel, start_idx:end_idx] += ied

    return Event(
        event_type=EventType.IED, timestamp=time_s,
        channel_id=channel, duration=dur_s,
        metadata={"synthetic": True, "type": "IED", "amplitude": amplitude},
    )

def generate_synthetic_recording(
    n_channels: int = 1,
    duration_s: float = 120.0,
    sample_rate: float = 1000.0,
    n_slow_waves: int = 15,
    n_ieds: int = 5,
    snr: float = 5.0,
    sw_amplitude: float = 500.0,
    sw_frequency: float = 1.0,
    ied_amplitude: float = 5000.0,
    seed: int = 42,
) -> tuple[NDArray[np.float64], list[Event], float]:
    """Generate a full synthetic recording with planted events.

    Returns:
        (signal, ground_truth_events, actual_snr)
    """
    rng = np.random.default_rng(seed)
    n_samples = int(duration_s * sample_rate)

    noise = generate_pink_noise(n_channels, n_samples, sample_rate, seed)
    noise_std = np.std(noise)
    noise_scale = sw_amplitude / (snr * noise_std) if snr > 0 else 0.0
    signal = noise * noise_scale

    events: list[Event] = []

    # Plant slow waves with minimum spacing
    min_spacing = 4.0
    margin = 3.0
    sw_times = _place_events(rng, n_slow_waves, margin, duration_s - margin, min_spacing)

    for t in sw_times:
        ch = rng.integers(0, n_channels)
        events.append(inject_slow_wave(signal, ch, t, sample_rate, sw_frequency, sw_amplitude))

    # Plant IEDs avoiding SWs
    ied_times = _place_events(
        rng, n_ieds, margin, duration_s - margin, min_spacing,
        avoid=sw_times, avoid_radius=2.0,
    )
    for t in ied_times:
        ch = rng.integers(0, n_channels)
        events.append(inject_ied(signal, ch, t, sample_rate, ied_amplitude))

    events.sort(key=lambda e: e.timestamp)
    actual_snr = sw_amplitude / (noise_scale * noise_std) if noise_scale > 0 else float("inf")

    logger.info(
        "Synthetic: %.0fs, %d ch, %d SWs, %d IEDs, SNR=%.1f",
        duration_s, n_channels, len(sw_times), len(ied_times), actual_snr,
    )
    return signal, events, actual_snr


def _place_events(
    rng, n: int, lo: float, hi: float, min_spacing: float,
    avoid: list[float] | None = None, avoid_radius: float = 0.0,
) -> list[float]:
    """Place n events in [lo, hi] with minimum spacing, optionally avoiding other times."""
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
    """Save synthetic recording in DNB .npz format."""
    path = Path(path)
    save_dict = {"continuous": signal, "sample_rate": sample_rate}
    if events:
        save_dict["gt_timestamps"] = np.array([e.timestamp for e in events])
        save_dict["gt_types"] = np.array([e.metadata.get("type", "unknown") for e in events])
        save_dict["gt_channels"] = np.array([e.channel_id for e in events])
    np.savez(str(path), **save_dict)
    logger.info("Saved synthetic recording to %s", path)
    return path
