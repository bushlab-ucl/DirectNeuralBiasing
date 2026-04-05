"""DNB closed-loop slow wave stimulation test.

Tests both offline (synthetic data) and live (NPlay/Cerebus) modes.
Logs all events to console and to a timestamped log file in ./logs/.

Usage:
    python test-file.py                           # offline only (no hardware)
    python test-file.py --live nplay              # + live NPlay
    python test-file.py --live nplay --channel 5  # single channel
    python test-file.py --live cerebus --inst-addr 192.168.0.1
    python test-file.py --no-live                 # skip live explicitly
    python test-file.py --seconds 30              # longer live run

Place pink_noise_short.wav in src/pythonlib/assets/ for audio stimulation.
"""

import argparse
import logging
import numpy as np
import tempfile
import os
import threading
import time
from math import pi
from pathlib import Path

import dnb
from dnb import Pipeline, FileSource, PipelineConfig, EventType, setup_logging
from dnb.modules import (
    WaveletConvolution, SlowWaveDetector, AudioStimulator,
    PowerEstimator, Downsampler,
)



ASSETS_DIR = Path(__file__).parent / "assets"
WAV_PATH = ASSETS_DIR / "pink_noise_short.wav"

logger = logging.getLogger("dnb.test")


# ============================================================
# 1. Synthetic slow wave generation
# ============================================================

def generate_slow_wave_recording(
    n_channels: int = 1,
    duration_s: float = 60.0,
    fs: float = 1000.0,
    so_freq: float = 1.0,
    so_amplitude: float = 500.0,
    noise_level: float = 50.0,
    seed: int = 42,
):
    """Generate a synthetic recording with clear slow oscillations."""
    rng = np.random.default_rng(seed)
    n_samples = int(duration_s * fs)
    t = np.arange(n_samples) / fs

    signal = np.zeros((n_channels, n_samples))
    for ch in range(n_channels):
        phase_offset = rng.uniform(0, 2 * pi)
        signal[ch] = so_amplitude * np.sin(2 * pi * so_freq * t + phase_offset)

    signal += rng.standard_normal(signal.shape) * noise_level
    return signal, fs


# ============================================================
# 2. Offline test
# ============================================================

def run_offline_test():
    print("=" * 60)
    print("OFFLINE TEST — synthetic slow waves")
    print("=" * 60)

    signal, fs = generate_slow_wave_recording(
        n_channels=1, duration_s=60.0, fs=1000.0,
        so_freq=1.0, so_amplitude=500.0, noise_level=50.0,
    )

    path = os.path.join(tempfile.mkdtemp(), "slow_wave_test.npz")
    np.savez(path, continuous=signal, sample_rate=fs)

    logger.info("Synthetic data: 1 channel, 60s @ %.0f Hz, 1 Hz slow wave", fs)

    has_wav = WAV_PATH.exists()
    modules = [
        WaveletConvolution(freq_min=0.5, freq_max=30, n_freqs=10),
        PowerEstimator(),
        SlowWaveDetector(
            target_phase=pi,             # negative peak of sine = pi
            phase_tolerance=0.15,        # tight: ~24ms window at 1 Hz
            freq_range=(0.5, 2.0),
            amp_min=100.0,
            amp_max=5000.0,
            backoff_s=8.0,               # one stim every 8s max
            stim2_delay_s=0.6,
            stim2_window_s=2.0,
            warmup_chunks=5,
        ),
    ]
    if has_wav:
        modules.append(AudioStimulator(
            wav_path=WAV_PATH,
            trigger_on=(EventType.STIM1,),  # only STIM1 plays audio
        ))
        logger.info("Audio stimulation enabled (STIM1 only): %s", WAV_PATH.name)
    else:
        logger.info("No audio file at %s — audio stim disabled", WAV_PATH)

    events = Pipeline(
        source=FileSource(path),
        modules=modules,
        config=PipelineConfig(sample_rate=fs, n_channels=1, chunk_duration=0.5),
    ).run_offline()

    stim1 = [e for e in events if e.event_type == EventType.STIM1]
    stim2 = [e for e in events if e.event_type == EventType.STIM2]

    logger.info("Results: %d STIM1, %d STIM2 events", len(stim1), len(stim2))

    if stim1:
        phases = [e.metadata.get("phase", float("nan")) for e in stim1]
        times = [e.timestamp for e in stim1]
        intervals = np.diff(times)
        logger.info("STIM1 times: %s", [f"{t:.2f}s" for t in times[:10]])
        logger.info("STIM1 phase: mean=%.2f rad, std=%.2f rad",
                     np.nanmean(phases), np.nanstd(phases))
        if len(intervals) > 0:
            logger.info("STIM1 intervals: mean=%.1fs, min=%.1fs, max=%.1fs",
                         np.mean(intervals), np.min(intervals), np.max(intervals))

    print(f"\n  STIM1: {len(stim1)}  |  STIM2: {len(stim2)}")
    if stim1:
        print(f"  PASS — slow wave stimulation working")
    else:
        print(f"  WARN — no stimulation events detected")

    return len(stim1) > 0


# ============================================================
# 3. Live test
# ============================================================

def make_source(kind, inst_addr="", client_addr="0.0.0.0"):
    from dnb import NPlaySource, CerebusSource
    if kind == "cerebus":
        return CerebusSource(inst_addr=inst_addr, client_addr=client_addr)
    return NPlaySource()


def detect_source(inst_addr="", client_addr="0.0.0.0"):
    try:
        import pycbsdk
    except ImportError:
        logger.info("pycbsdk not installed — pip install direct-neural-biasing[live]")
        return None, 0

    config = PipelineConfig(sample_rate=30000, n_channels=83, chunk_duration=0.2)
    for kind in ["nplay", "cerebus"]:
        try:
            src = make_source(kind, inst_addr, client_addr)
            src.connect(config)
            time.sleep(1.5)
            chunk = src.read_chunk()
            src.close()
            if chunk is not None:
                logger.info("%s: data flowing (%d channels)", kind, chunk.n_channels)
                return kind, chunk.n_channels
            else:
                logger.info("%s: connected but no data", kind)
        except Exception as e:
            logger.info("%s: %s", kind, e)
    return None, 0


def run_live_test(kind, n_channels, run_seconds, channel, inst_addr, client_addr):
    print(f"\n{'=' * 60}")
    label = f"ch={channel}" if channel is not None else f"{n_channels} ch"
    print(f"LIVE TEST — {kind} ({label}, {run_seconds}s)")
    print("=" * 60)

    det_channels = [channel] if channel is not None else None

    config = PipelineConfig(
        sample_rate=30000,
        n_channels=n_channels,
        chunk_duration=0.5,
    )

    has_wav = WAV_PATH.exists()

    modules = [
        Downsampler(target_rate=500.0),
        WaveletConvolution(
            freq_min=0.5, freq_max=30, n_freqs=10,
            channels=det_channels,
        ),
        PowerEstimator(),
        SlowWaveDetector(
            target_phase=0.0,
            phase_tolerance=0.15,
            freq_range=(0.5, 2.0),
            hf_freq_range=(10.0, 30.0),
            amp_min=50.0,
            amp_max=10000.0,
            hf_ratio_max=0.5,
            backoff_s=5.0,
            stim2_delay_s=0.6,
            stim2_window_s=2.0,
            warmup_chunks=10,
            channels=det_channels,
        ),
    ]
    if has_wav:
        modules.append(AudioStimulator(
            wav_path=WAV_PATH,
            trigger_on=(EventType.STIM1,),
        ))
        logger.info("Audio stimulation enabled (STIM1 only): %s", WAV_PATH.name)
    else:
        logger.info("No audio file at %s — stim events logged only", WAV_PATH)

    source = make_source(kind, inst_addr, client_addr)
    pipeline = Pipeline(source=source, modules=modules, config=config)

    events = []
    chunk_count = [0]
    latencies = []

    def on_event(event):
        events.append(event)
        if len(events) <= 30:
            logger.info(
                "EVENT [%3d] %s ch=%d t=%.3fs phase=%.2f amp=%.1f",
                len(events), event.event_type.name, event.channel_id,
                event.timestamp,
                event.metadata.get("phase", float("nan")),
                event.metadata.get("amplitude", float("nan")),
            )

    pipeline.on_event(None, on_event)

    original_process = pipeline._process_chunk

    def instrumented_process(chunk):
        t0 = time.perf_counter()
        result = original_process(chunk)
        dt = (time.perf_counter() - t0) * 1000
        latencies.append(dt)
        i = chunk_count[0]
        chunk_count[0] += 1
        if i < 3 or i % 20 == 0:
            logger.info("chunk %4d: shape=%s ev=%d latency=%.1fms",
                         i, chunk.samples.shape, len(result.events), dt)
        return result

    pipeline._process_chunk = instrumented_process

    logger.info("Running for %ds...", run_seconds)

    timer = threading.Timer(run_seconds, pipeline.stop)
    timer.start()
    t_wall_start = time.perf_counter()
    try:
        pipeline.run_online()
    except KeyboardInterrupt:
        pipeline.stop()
    finally:
        timer.cancel()
    t_wall = time.perf_counter() - t_wall_start

    stim1 = [e for e in events if e.event_type == EventType.STIM1]
    stim2 = [e for e in events if e.event_type == EventType.STIM2]

    print(f"\n{'─' * 60}")
    print("SUMMARY")
    print(f"{'─' * 60}")
    logger.info("Wall time: %.1fs", t_wall)
    logger.info("Chunks processed: %d", chunk_count[0])
    logger.info("STIM1: %d  |  STIM2: %d", len(stim1), len(stim2))

    if latencies:
        lat = np.array(latencies)
        logger.info("Latency: mean=%.1fms median=%.1fms p95=%.1fms max=%.1fms",
                     np.mean(lat), np.median(lat), np.percentile(lat, 95), np.max(lat))
        budget = config.chunk_duration * 1000
        overruns = int(np.sum(lat > budget))
        logger.info("Budget: %.0fms/chunk, overruns: %d/%d", budget, overruns, len(lat))

    if stim1:
        phases = [e.metadata.get("phase", float("nan")) for e in stim1]
        times = [e.timestamp for e in stim1]
        intervals = np.diff(times) if len(times) > 1 else []
        logger.info("STIM1 phase: mean=%.2f std=%.2f", np.nanmean(phases), np.nanstd(phases))
        if len(intervals) > 0:
            logger.info("STIM1 intervals: mean=%.1fs min=%.1fs max=%.1fs",
                         np.mean(intervals), np.min(intervals), np.max(intervals))

    return len(stim1)


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DNB slow wave stimulation test")
    parser.add_argument("--live", choices=["nplay", "cerebus"], default=None)
    parser.add_argument("--no-live", action="store_true")
    parser.add_argument("--inst-addr", default="")
    parser.add_argument("--channels", type=int, default=83)
    parser.add_argument("--channel", type=int, default=None)
    parser.add_argument("--seconds", type=int, default=15)
    parser.add_argument("--log-dir", default="./logs")
    args = parser.parse_args()

    log_path = setup_logging(log_dir=args.log_dir)
    logger.info("DNB v%s — slow wave stimulation test", dnb.__version__)
    logger.info("Audio file: %s (exists=%s)", WAV_PATH, WAV_PATH.exists())

    run_offline_test()

    if args.no_live:
        logger.info("Skipping live test (--no-live)")
    elif args.live:
        run_live_test(
            kind=args.live, n_channels=args.channels,
            run_seconds=args.seconds, channel=args.channel,
            inst_addr=args.inst_addr, client_addr="0.0.0.0",
        )
    else:
        logger.info("Auto-detecting live source...")
        kind, n_ch = detect_source(inst_addr=args.inst_addr)
        if kind:
            run_live_test(
                kind=kind, n_channels=n_ch,
                run_seconds=args.seconds, channel=args.channel,
                inst_addr=args.inst_addr, client_addr="0.0.0.0",
            )
        else:
            logger.info("No live source found — skipping live test")

    if log_path:
        print(f"\nLog file: {log_path}")