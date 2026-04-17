"""Test data generator for offline smoke tests."""

from __future__ import annotations

import tempfile
from math import pi
from pathlib import Path

import numpy as np

from dnb.validation.synthetic import (
    generate_pink_noise, inject_slow_wave, inject_ied, save_synthetic,
)


class TestData:
    def __init__(self, output_dir: str | Path | None = None):
        if output_dir is not None:
            self.dir = Path(output_dir)
            self.dir.mkdir(parents=True, exist_ok=True)
            self._tmpdir = None
        else:
            self._tmpdir = tempfile.TemporaryDirectory()
            self.dir = Path(self._tmpdir.name)

    def clean_sine(
        self, fs: float = 1000.0, duration_s: float = 30.0,
        frequency: float = 1.0, amplitude: float = 500.0,
    ) -> Path:
        n = int(duration_s * fs)
        t = np.arange(n) / fs
        signal = amplitude * np.sin(2 * pi * frequency * t)
        path = self.dir / "clean_sine.npz"
        save_synthetic(path, signal, fs)
        return path

    def slow_waves(
        self, snr: float = 5.0, n_slow_waves: int = 15,
        duration_s: float = 120.0, sample_rate: float = 1000.0, seed: int = 42,
    ) -> tuple[Path, list]:
        from dnb.validation.synthetic import generate_synthetic_recording
        signal, gt_events, _ = generate_synthetic_recording(
            duration_s=duration_s, sample_rate=sample_rate,
            n_slow_waves=n_slow_waves, n_ieds=0, snr=snr, seed=seed,
        )
        path = self.dir / f"sw_snr{snr:.1f}.npz"
        save_synthetic(path, signal, sample_rate, gt_events)
        return path, gt_events

    def slow_waves_with_ieds(
        self, snr: float = 5.0, n_slow_waves: int = 15, n_ieds: int = 10,
        n_ieds_near_sw: int = 5, ied_near_offset_s: float = 0.5,
        duration_s: float = 120.0, sample_rate: float = 1000.0,
        sw_amplitude: float = 500.0, ied_amplitude: float = 3000.0, seed: int = 42,
    ) -> tuple[Path, list]:
        rng = np.random.default_rng(seed)
        n_samples = int(duration_s * sample_rate)

        noise = generate_pink_noise(n_samples, sample_rate, seed)
        noise_std = np.std(noise)
        noise_scale = sw_amplitude / (snr * noise_std) if snr > 0 else 0.0
        signal = noise * noise_scale

        events = []
        min_spacing = 4.0
        margin = 3.0
        sw_times = _place_events(rng, n_slow_waves, margin, duration_s - margin, min_spacing)
        for t in sw_times:
            events.append(inject_slow_wave(signal, t, sample_rate, 1.0, sw_amplitude))

        near_count = min(n_ieds_near_sw, len(sw_times))
        near_sw_indices = rng.choice(len(sw_times), size=near_count, replace=False)
        near_ied_times = []
        for idx in near_sw_indices:
            offset = rng.choice([-1, 1]) * ied_near_offset_s
            t_ied = sw_times[idx] + offset
            if margin < t_ied < duration_s - margin:
                near_ied_times.append(t_ied)
                events.append(inject_ied(signal, t_ied, sample_rate, ied_amplitude))

        n_random_ieds = n_ieds - len(near_ied_times)
        all_avoid = sw_times + near_ied_times
        random_ied_times = _place_events(
            rng, n_random_ieds, margin, duration_s - margin, 8.0,
            avoid=all_avoid, avoid_radius=6.0,
        )
        for t in random_ied_times:
            events.append(inject_ied(signal, t, sample_rate, ied_amplitude))

        events.sort(key=lambda e: e.timestamp)
        path = self.dir / f"sw_ied_snr{snr:.1f}.npz"
        save_synthetic(path, signal, sample_rate, events)
        return path, events


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