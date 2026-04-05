"""Synthetic data generation and validation.

Generates neural-like signals with known, planted slow waves and IEDs
so that detector accuracy can be measured against ground truth at
varying noise levels.

Usage:
    from dnb.validation.synthetic import (
        generate_synthetic_recording,
        run_snr_sweep,
        save_debug_figures,
    )

    # Single recording
    data, events = generate_synthetic_recording(snr=5.0)

    # Full SNR sweep with figures
    results = run_snr_sweep(
        snr_levels=[1, 2, 3, 5, 10],
        output_dir="./validation_output",
    )
"""

from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass
from math import pi
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from dnb.core.types import Event, EventType

logger = logging.getLogger(__name__)


def generate_pink_noise(
    n_channels: int,
    n_samples: int,
    sample_rate: float,
    seed: int = 42,
) -> NDArray[np.float64]:
    """Generate 1/f (pink) noise matching neural spectral profile.

    Args:
        n_channels: Number of channels.
        n_samples: Total samples.
        sample_rate: Sampling rate in Hz.
        seed: Random seed for reproducibility.

    Returns:
        Array of shape (n_channels, n_samples) with 1/f noise.
    """
    rng = np.random.default_rng(seed)

    # Generate white noise in frequency domain, apply 1/f filter
    freqs = np.fft.rfftfreq(n_samples, d=1.0 / sample_rate)
    freqs[0] = 1.0  # avoid division by zero

    noise = np.zeros((n_channels, n_samples))
    for ch in range(n_channels):
        white = rng.standard_normal(n_samples)
        white_fft = np.fft.rfft(white)
        # 1/f scaling
        pink_fft = white_fft / np.sqrt(freqs)
        noise[ch] = np.fft.irfft(pink_fft, n=n_samples)

    # Normalise to unit variance
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
    """Plant a known slow wave at a specific time.

    The slow wave is a windowed sinusoid (Hann-windowed) injected into
    the signal.

    Args:
        signal: Signal array (n_channels, n_samples), modified in-place.
        channel: Channel to inject into.
        time_s: Centre time of the slow wave in seconds.
        sample_rate: Sampling rate in Hz.
        frequency: Slow wave frequency in Hz.
        amplitude: Peak amplitude of the slow wave.
        n_cycles: Number of cycles in the burst.

    Returns:
        Ground truth Event marking the injection.
    """
    duration = n_cycles / frequency
    half_dur = duration / 2.0
    start_s = time_s - half_dur
    end_s = time_s + half_dur

    start_idx = max(0, int(start_s * sample_rate))
    end_idx = min(signal.shape[1], int(end_s * sample_rate))
    n = end_idx - start_idx

    if n <= 0:
        return Event(
            event_type=EventType.STIM1, timestamp=time_s,
            channel_id=channel, duration=duration,
            metadata={"synthetic": True, "type": "SW"},
        )

    t = np.arange(n) / sample_rate
    # Hann-windowed sinusoid
    window = np.hanning(n)
    sw = amplitude * np.sin(2 * pi * frequency * t) * window
    signal[channel, start_idx:end_idx] += sw

    return Event(
        event_type=EventType.STIM1,
        timestamp=time_s,
        channel_id=channel,
        duration=duration,
        metadata={"synthetic": True, "type": "SW", "amplitude": amplitude,
                  "frequency": frequency},
    )


def inject_ied(
    signal: NDArray[np.float64],
    channel: int,
    time_s: float,
    sample_rate: float,
    amplitude: float = 2000.0,
    duration_ms: float = 70.0,
) -> Event:
    """Plant a synthetic interictal epileptiform discharge (IED).

    IEDs are sharp transients with high-frequency content — modelled as
    a sharp spike followed by a slow wave (spike-and-wave complex).

    Args:
        signal: Signal array, modified in-place.
        channel: Channel to inject into.
        time_s: Time of the spike peak in seconds.
        sample_rate: Sampling rate in Hz.
        amplitude: Peak spike amplitude.
        duration_ms: Total IED duration in milliseconds.

    Returns:
        Ground truth Event.
    """
    dur_s = duration_ms / 1000.0
    start_idx = max(0, int((time_s - dur_s * 0.2) * sample_rate))
    end_idx = min(signal.shape[1], int((time_s + dur_s * 0.8) * sample_rate))
    n = end_idx - start_idx
    if n <= 0:
        return Event(
            event_type=EventType.THRESHOLD_CROSSING, timestamp=time_s,
            channel_id=channel, duration=dur_s,
            metadata={"synthetic": True, "type": "IED"},
        )

    t = np.arange(n) / sample_rate

    # Sharp spike (narrow Gaussian)
    spike_sigma = 0.005  # 5ms
    spike = amplitude * np.exp(-((t - dur_s * 0.2) ** 2) / (2 * spike_sigma ** 2))

    # Following slow wave (opposite polarity)
    sw_centre = dur_s * 0.5
    sw_sigma = 0.03  # 30ms
    slow = -amplitude * 0.4 * np.exp(-((t - sw_centre) ** 2) / (2 * sw_sigma ** 2))

    signal[channel, start_idx:end_idx] += spike + slow

    return Event(
        event_type=EventType.THRESHOLD_CROSSING,
        timestamp=time_s,
        channel_id=channel,
        duration=dur_s,
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
    ied_amplitude: float = 2000.0,
    seed: int = 42,
) -> tuple[NDArray[np.float64], list[Event], float]:
    """Generate a full synthetic recording with planted events.

    Args:
        n_channels: Number of channels.
        duration_s: Recording duration in seconds.
        sample_rate: Sampling rate in Hz.
        n_slow_waves: Number of slow waves to plant.
        n_ieds: Number of IEDs to plant.
        snr: Signal-to-noise ratio (amplitude ratio, not dB).
        sw_amplitude: Slow wave amplitude before SNR scaling.
        sw_frequency: Slow wave frequency in Hz.
        ied_amplitude: IED spike amplitude before SNR scaling.
        seed: Random seed.

    Returns:
        Tuple of (signal, ground_truth_events, actual_snr).
    """
    rng = np.random.default_rng(seed)
    n_samples = int(duration_s * sample_rate)

    # Generate 1/f background noise
    noise = generate_pink_noise(n_channels, n_samples, sample_rate, seed)

    # Scale noise so that signal/noise = snr
    noise_std = np.std(noise)
    signal_amplitude = sw_amplitude
    noise_scale = signal_amplitude / (snr * noise_std) if snr > 0 else 0.0
    signal = noise * noise_scale

    events: list[Event] = []

    # Plant slow waves at random times (with minimum spacing)
    min_spacing = 4.0  # seconds
    margin = 3.0  # seconds from edges
    sw_times = []
    attempts = 0
    while len(sw_times) < n_slow_waves and attempts < n_slow_waves * 100:
        t = rng.uniform(margin, duration_s - margin)
        if all(abs(t - existing) > min_spacing for existing in sw_times):
            sw_times.append(t)
        attempts += 1
    sw_times.sort()

    for t in sw_times:
        ch = rng.integers(0, n_channels)
        ev = inject_slow_wave(
            signal, ch, t, sample_rate,
            frequency=sw_frequency, amplitude=sw_amplitude,
        )
        events.append(ev)

    # Plant IEDs at random times
    ied_times = []
    attempts = 0
    while len(ied_times) < n_ieds and attempts < n_ieds * 100:
        t = rng.uniform(margin, duration_s - margin)
        # Don't overlap with SWs
        if all(abs(t - sw) > 2.0 for sw in sw_times):
            if all(abs(t - existing) > min_spacing for existing in ied_times):
                ied_times.append(t)
        attempts += 1
    ied_times.sort()

    for t in ied_times:
        ch = rng.integers(0, n_channels)
        ev = inject_ied(signal, ch, t, sample_rate, amplitude=ied_amplitude)
        events.append(ev)

    events.sort(key=lambda e: e.timestamp)

    # Compute actual SNR
    actual_snr = sw_amplitude / (noise_scale * noise_std) if noise_scale > 0 else float("inf")

    logger.info(
        "Generated synthetic recording: %.0fs, %d channels, %d SWs, %d IEDs, SNR=%.1f",
        duration_s, n_channels, len(sw_times), len(ied_times), actual_snr,
    )
    return signal, events, actual_snr


def save_synthetic(
    path: str | Path,
    signal: NDArray[np.float64],
    sample_rate: float,
    events: list[Event] | None = None,
) -> Path:
    """Save synthetic recording in DNB .npz format.

    Args:
        path: Output file path.
        signal: Signal array (n_channels, n_samples).
        sample_rate: Sampling rate in Hz.
        events: Optional ground truth events to save alongside.

    Returns:
        Path to the saved file.
    """
    path = Path(path)
    save_dict = {
        "continuous": signal,
        "sample_rate": sample_rate,
    }
    if events:
        save_dict["gt_timestamps"] = np.array([e.timestamp for e in events])
        save_dict["gt_types"] = np.array(
            [e.metadata.get("type", "unknown") for e in events])
        save_dict["gt_channels"] = np.array([e.channel_id for e in events])

    np.savez(str(path), **save_dict)
    logger.info("Saved synthetic recording to %s", path)
    return path


@dataclass
class SNRResult:
    """Result of detection at a single SNR level."""
    snr: float
    n_planted_sw: int
    n_planted_ied: int
    n_detected: int
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    timing_errors_ms: list[float]


def run_snr_sweep(
    snr_levels: list[float] | None = None,
    output_dir: str | Path = "./validation_output",
    duration_s: float = 120.0,
    sample_rate: float = 1000.0,
    n_slow_waves: int = 15,
    n_ieds: int = 5,
    time_tolerance: float = 0.5,
    **detector_kwargs,
) -> list[SNRResult]:
    """Run detection at multiple SNR levels and collect metrics.

    For each SNR level, generates a synthetic recording, runs the
    pipeline, matches detections to ground truth, and records metrics.

    Args:
        snr_levels: List of SNR values to test.
        output_dir: Directory for output files and figures.
        duration_s: Recording duration per SNR level.
        sample_rate: Sampling rate.
        n_slow_waves: Number of SWs to plant per recording.
        n_ieds: Number of IEDs per recording.
        time_tolerance: Matching tolerance in seconds.
        **detector_kwargs: Override SlowWaveDetector parameters.

    Returns:
        List of SNRResult for each level.
    """
    from dnb import Pipeline, FileSource, PipelineConfig
    from dnb.modules import WaveletConvolution, PowerEstimator, SlowWaveDetector
    from dnb.validation.ground_truth import (
        Annotation, validate,
    )

    if snr_levels is None:
        snr_levels = [1.0, 2.0, 3.0, 5.0, 10.0]

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[SNRResult] = []

    for snr in snr_levels:
        logger.info("=== SNR sweep: SNR = %.1f ===", snr)

        signal, gt_events, actual_snr = generate_synthetic_recording(
            n_channels=1, duration_s=duration_s, sample_rate=sample_rate,
            n_slow_waves=n_slow_waves, n_ieds=n_ieds, snr=snr,
            seed=int(snr * 1000),
        )

        # Save to temp file
        tmp_path = output_dir / f"synthetic_snr{snr:.1f}.npz"
        save_synthetic(tmp_path, signal, sample_rate, gt_events)

        # Default detector params
        det_params = dict(
            target_phase=pi,
            phase_tolerance=0.3,
            freq_range=(0.5, 2.0),
            amp_min=50.0,
            amp_max=10000.0,
            backoff_s=3.0,
            warmup_chunks=3,
            event_window_s=1.0,
        )
        det_params.update(detector_kwargs)

        # Run pipeline
        pipeline = Pipeline(
            source=FileSource(str(tmp_path)),
            modules=[
                WaveletConvolution(freq_min=0.5, freq_max=30, n_freqs=10),
                PowerEstimator(),
                SlowWaveDetector(**det_params),
            ],
            config=PipelineConfig(
                sample_rate=sample_rate, n_channels=1,
                chunk_duration=0.5,
            ),
        )
        detections = pipeline.run_offline()

        # Convert ground truth events to Annotations for validation
        annotations = []
        for ev in gt_events:
            ann_type = ev.metadata.get("type", "SW")
            annotations.append(Annotation(
                timestamp=ev.timestamp,
                duration=ev.duration,
                channel=ev.channel_id,
                event_type=ann_type,
            ))

        # Only match STIM1 detections (not STIM2)
        stim1_detections = [e for e in detections if e.event_type == EventType.STIM1]

        report = validate(
            stim1_detections, annotations,
            time_tolerance=time_tolerance,
            target_annotation_type="SW",
        )
        report._compute_metrics()
        m = report.metrics

        timing_errors = [me.time_error * 1000 for me in report.matched]

        result = SNRResult(
            snr=actual_snr,
            n_planted_sw=len([e for e in gt_events
                              if e.metadata.get("type") == "SW"]),
            n_planted_ied=len([e for e in gt_events
                               if e.metadata.get("type") == "IED"]),
            n_detected=len(stim1_detections),
            true_positives=int(m.get("true_positives", 0)),
            false_positives=int(m.get("false_positives", 0)),
            false_negatives=int(m.get("false_negatives", 0)),
            precision=m.get("precision", 0.0),
            recall=m.get("recall", 0.0),
            f1=m.get("f1", 0.0),
            timing_errors_ms=timing_errors,
        )
        results.append(result)

        logger.info(
            "  SNR=%.1f: P=%.2f R=%.2f F1=%.2f (TP=%d FP=%d FN=%d)",
            actual_snr, result.precision, result.recall, result.f1,
            result.true_positives, result.false_positives, result.false_negatives,
        )

    # Save summary
    _save_sweep_summary(results, output_dir)

    return results


def _save_sweep_summary(results: list[SNRResult], output_dir: Path) -> None:
    """Save sweep results to CSV and npz."""
    import csv

    csv_path = output_dir / "snr_sweep_results.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "snr", "n_sw", "n_ied", "n_detected",
            "tp", "fp", "fn", "precision", "recall", "f1",
            "timing_error_mean_ms", "timing_error_std_ms",
        ])
        for r in results:
            t_mean = float(np.mean(r.timing_errors_ms)) if r.timing_errors_ms else 0.0
            t_std = float(np.std(r.timing_errors_ms)) if r.timing_errors_ms else 0.0
            writer.writerow([
                f"{r.snr:.1f}", r.n_planted_sw, r.n_planted_ied, r.n_detected,
                r.true_positives, r.false_positives, r.false_negatives,
                f"{r.precision:.3f}", f"{r.recall:.3f}", f"{r.f1:.3f}",
                f"{t_mean:.1f}", f"{t_std:.1f}",
            ])
    logger.info("Sweep summary saved to %s", csv_path)


def save_debug_figures(
    results: list[SNRResult],
    output_dir: str | Path = "./validation_output",
) -> list[Path]:
    """Generate debug figures from SNR sweep results.

    Produces:
    1. Precision/Recall/F1 vs SNR
    2. Timing error distribution per SNR
    3. Detection counts vs SNR

    Requires matplotlib.

    Args:
        results: Output from run_snr_sweep().
        output_dir: Directory for figure files.

    Returns:
        List of paths to generated figure files.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning(
            "matplotlib not available — cannot generate figures. "
            "Install with: pip install matplotlib"
        )
        return []

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    snrs = [r.snr for r in results]

    # --- Figure 1: Precision / Recall / F1 vs SNR ---
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(snrs, [r.precision for r in results], "o-", label="Precision", linewidth=2)
    ax.plot(snrs, [r.recall for r in results], "s-", label="Recall", linewidth=2)
    ax.plot(snrs, [r.f1 for r in results], "^-", label="F1", linewidth=2)
    ax.set_xlabel("Signal-to-Noise Ratio", fontsize=12)
    ax.set_ylabel("Score", fontsize=12)
    ax.set_title("Slow Wave Detection Performance vs SNR", fontsize=14)
    ax.set_ylim(-0.05, 1.05)
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    p = output_dir / "precision_recall_f1_vs_snr.png"
    fig.savefig(str(p), dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(p)

    # --- Figure 2: Timing error box plot ---
    timing_data = [r.timing_errors_ms for r in results if r.timing_errors_ms]
    timing_labels = [f"SNR={r.snr:.0f}" for r in results if r.timing_errors_ms]

    if timing_data:
        fig, ax = plt.subplots(figsize=(8, 5))
        bp = ax.boxplot(timing_data, labels=timing_labels, patch_artist=True)
        for patch in bp["boxes"]:
            patch.set_facecolor("#4C72B0")
            patch.set_alpha(0.7)
        ax.set_xlabel("SNR Level", fontsize=12)
        ax.set_ylabel("Timing Error (ms)", fontsize=12)
        ax.set_title("Detection Timing Error by SNR", fontsize=14)
        ax.axhline(y=0, color="red", linestyle="--", alpha=0.5, label="Perfect timing")
        ax.legend()
        ax.grid(True, alpha=0.3, axis="y")
        p = output_dir / "timing_error_vs_snr.png"
        fig.savefig(str(p), dpi=150, bbox_inches="tight")
        plt.close(fig)
        paths.append(p)

    # --- Figure 3: Detection counts ---
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(snrs))
    width = 0.25
    ax.bar(x - width, [r.true_positives for r in results], width,
           label="True Positives", color="#4C72B0")
    ax.bar(x, [r.false_positives for r in results], width,
           label="False Positives", color="#DD8452")
    ax.bar(x + width, [r.false_negatives for r in results], width,
           label="False Negatives", color="#55A868")
    ax.set_xlabel("SNR Level", fontsize=12)
    ax.set_ylabel("Count", fontsize=12)
    ax.set_title("Detection Breakdown by SNR", fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{s:.0f}" for s in snrs])
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    p = output_dir / "detection_counts_vs_snr.png"
    fig.savefig(str(p), dpi=150, bbox_inches="tight")
    plt.close(fig)
    paths.append(p)

    logger.info("Saved %d debug figures to %s", len(paths), output_dir)
    return paths
