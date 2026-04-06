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
    generate_synthetic_recording,
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
        n_ieds: int = 8,
        duration_s: float = 120.0,
        sample_rate: float = 1000.0,
        ied_amplitude: float = 3000.0,
        seed: int = 42,
    ) -> tuple[Path, list]:
        """Pink noise + planted slow waves + IEDs."""
        signal, gt_events, actual_snr = generate_synthetic_recording(
            n_channels=1, duration_s=duration_s, sample_rate=sample_rate,
            n_slow_waves=n_slow_waves, n_ieds=n_ieds,
            snr=snr, ied_amplitude=ied_amplitude, seed=seed,
        )
        path = self.dir / f"sw_ied_snr{snr:.1f}.npz"
        save_synthetic(path, signal, sample_rate, gt_events)
        return path, gt_events

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
        signal, gt_events, _ = generate_synthetic_recording(
            n_channels=1, duration_s=duration_s, sample_rate=sample_rate,
            n_slow_waves=n_slow_waves, n_ieds=n_ieds,
            snr=snr, seed=seed,
        )
        path = self.dir / "short_segment.npz"
        save_synthetic(path, signal, sample_rate, gt_events)
        return path, gt_events, signal
