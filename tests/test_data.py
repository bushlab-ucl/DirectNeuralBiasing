"""Test data generator for offline smoke tests.

Generates synthetic recordings programmatically. All files go into
a temp directory that's cleaned up automatically, or into a specified
output directory.

Usage (from notebook):
    from test_data import TestData
    td = TestData()
    path = td.clean_sine()
    path = td.slow_waves(snr=5.0)
    path = td.slow_waves_with_ieds(snr=5.0)
"""

from __future__ import annotations

import tempfile
from math import pi
from pathlib import Path

import numpy as np

from dnb.validation.synthetic import (
    generate_pink_noise,
    inject_slow_wave,
    inject_ied,
    save_synthetic,
)


class TestData:
    """Generates and caches synthetic test recordings.

    All files are saved into a temp directory by default.
    Pass output_dir to keep them somewhere persistent.
    """

    def __init__(self, output_dir: str | Path | None = None):
        if output_dir is not None:
            self.dir = Path(output_dir)
            self.dir.mkdir(parents=True, exist_ok=True)
            self._tmpdir = None
        else:
            self._tmpdir = tempfile.TemporaryDirectory()
            self.dir = Path(self._tmpdir.name)

    def clean_sine(
        self,
        fs: float = 1000.0,
        duration_s: float = 30.0,
        frequency: float = 1.0,
        amplitude: float = 500.0,
    ) -> Path:
        """Clean sine wave — no noise, known phase for verification."""
        n = int(duration_s * fs)
        t = np.arange(n) / fs
        signal = amplitude * np.sin(2 * pi * frequency * t).reshape(1, -1)
        path = self.dir / "clean_sine.npz"
        save_synthetic(path, signal, fs)
        return path

    def slow_waves(
        self,
        snr: float = 5.0,
        n_slow_waves: int = 15,
        duration_s: float = 120.0,
        sample_rate: float = 1000.0,
        seed: int = 42,
    ) -> tuple[Path, list]:
        """Pink noise + planted slow waves, no IEDs."""
        from dnb.validation.synthetic import generate_synthetic_recording
        signal, gt_events, actual_snr = generate_synthetic_recording(
            n_channels=1, duration_s=duration_s, sample_rate=sample_rate,
            n_slow_waves=n_slow_waves, n_ieds=0,
            snr=snr, seed=seed,
        )
        path = self.dir / f"sw_snr{snr:.1f}.npz"
        save_synthetic(path, signal, sample_rate, gt_events)
        return path, gt_events

    def slow_waves_with_ieds(
        self,
        snr: float = 5.0,
        n_slow_waves: int = 15,
        n_ieds: int = 10,
        n_ieds_near_sw: int = 5,
        ied_near_offset_s: float = 0.5,
        duration_s: float = 120.0,
        sample_rate: float = 1000.0,
        sw_amplitude: float = 500.0,
        ied_amplitude: float = 3000.0,
        seed: int = 42,
    ) -> tuple[Path, list]:
        """Pink noise + planted slow waves + IEDs.

        Some IEDs are deliberately placed close to slow waves so that
        the inhibition logic has something meaningful to block.

        Args:
            n_ieds_near_sw: How many IEDs to place near slow waves.
            ied_near_offset_s: Time offset from SW centre for near-IEDs.
        """
        rng = np.random.default_rng(seed)
        n_samples = int(duration_s * sample_rate)

        # Generate pink noise background
        noise = generate_pink_noise(1, n_samples, sample_rate, seed)
        noise_std = np.std(noise)
        noise_scale = sw_amplitude / (snr * noise_std) if snr > 0 else 0.0
        signal = noise * noise_scale

        events = []

        # Place slow waves
        min_spacing = 4.0
        margin = 3.0
        sw_times = _place_events(rng, n_slow_waves, margin, duration_s - margin, min_spacing)
        for t in sw_times:
            events.append(inject_slow_wave(signal, 0, t, sample_rate, 1.0, sw_amplitude))

        # Place IEDs deliberately near some slow waves
        near_count = min(n_ieds_near_sw, len(sw_times))
        near_sw_indices = rng.choice(len(sw_times), size=near_count, replace=False)
        near_ied_times = []
        for idx in near_sw_indices:
            offset = rng.choice([-1, 1]) * ied_near_offset_s
            t_ied = sw_times[idx] + offset
            if margin < t_ied < duration_s - margin:
                near_ied_times.append(t_ied)
                events.append(inject_ied(signal, 0, t_ied, sample_rate, ied_amplitude))

        # Place remaining IEDs randomly, well away from SWs
        n_random_ieds = n_ieds - len(near_ied_times)
        all_avoid = sw_times + near_ied_times
        random_ied_times = _place_events(
            rng, n_random_ieds, margin, duration_s - margin, 8.0,
            avoid=all_avoid, avoid_radius=6.0,
        )
        for t in random_ied_times:
            events.append(inject_ied(signal, 0, t, sample_rate, ied_amplitude))

        events.sort(key=lambda e: e.timestamp)
        path = self.dir / f"sw_ied_snr{snr:.1f}.npz"
        save_synthetic(path, signal, sample_rate, events)
        return path, events

    def snr_sweep(
        self,
        snr_levels: list[float] | None = None,
        n_slow_waves: int = 15,
        duration_s: float = 120.0,
        sample_rate: float = 1000.0,
    ) -> list[tuple[float, Path, list]]:
        """Generate recordings at multiple SNR levels.

        Returns list of (actual_snr, path, gt_events).
        """
        from dnb.validation.synthetic import generate_synthetic_recording
        if snr_levels is None:
            snr_levels = [1.0, 2.0, 3.0, 5.0, 10.0]

        results = []
        for snr in snr_levels:
            signal, gt_events, actual_snr = generate_synthetic_recording(
                n_channels=1, duration_s=duration_s, sample_rate=sample_rate,
                n_slow_waves=n_slow_waves, n_ieds=0,
                snr=snr, seed=int(snr * 1000),
            )
            path = self.dir / f"snr_sweep_{snr:.1f}.npz"
            save_synthetic(path, signal, sample_rate, gt_events)
            results.append((actual_snr, path, gt_events))

        return results

    def short_segment(
        self,
        snr: float = 5.0,
        n_slow_waves: int = 3,
        n_ieds: int = 1,
        duration_s: float = 20.0,
        sample_rate: float = 1000.0,
        seed: int = 123,
    ) -> tuple[Path, list, np.ndarray]:
        """Short segment for wavelet inspection.

        Returns (path, gt_events, raw_signal).
        """
        from dnb.validation.synthetic import generate_synthetic_recording
        signal, gt_events, _ = generate_synthetic_recording(
            n_channels=1, duration_s=duration_s, sample_rate=sample_rate,
            n_slow_waves=n_slow_waves, n_ieds=n_ieds,
            snr=snr, seed=seed,
        )
        path = self.dir / "short_segment.npz"
        save_synthetic(path, signal, sample_rate, gt_events)
        return path, gt_events, signal


def _place_events(
    rng, n: int, lo: float, hi: float, min_spacing: float,
    avoid: list[float] | None = None, avoid_radius: float = 0.0,
) -> list[float]:
    """Place n events in [lo, hi] with minimum spacing."""
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