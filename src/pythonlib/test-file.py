"""DNB smoke test — offline + live.

Run from src/pythonlib/:
    python test-file.py
    python test-file.py --live nplay
    python test-file.py --live nplay --channel 5
    python test-file.py --live cerebus --inst-addr 192.168.0.1
    python test-file.py --no-live
"""

import argparse
import numpy as np
import tempfile
import os
import threading
import time

from dnb import Pipeline, FileSource, PipelineConfig, EventType
from dnb.modules import WaveletConvolution, EventDetector, PowerEstimator

# ============================================================
# 1. Offline test
# ============================================================

def run_offline_test():
    print("=" * 60)
    print("OFFLINE TEST — synthetic burst")
    print("=" * 60)

    rng = np.random.default_rng(42)
    fs = 30000.0
    n = int(10.0 * fs)
    t = np.arange(n) / fs
    data = rng.standard_normal((4, n)) * 0.5
    data[0, int(7.0*fs):int(7.2*fs)] += 15 * np.sin(2*np.pi*120*t[int(7.0*fs):int(7.2*fs)])

    path = os.path.join(tempfile.mkdtemp(), "test.npz")
    np.savez(path, continuous=data, sample_rate=fs)

    print(f"  4 channels, 10s @ {fs:.0f} Hz")
    print(f"  Planted burst: ch=0, t=7.0-7.2s, 120 Hz\n")

    events = Pipeline(
        source=FileSource(path),
        modules=[
            WaveletConvolution(freq_min=10, freq_max=200, n_freqs=15),
            PowerEstimator(),
            EventDetector(
                event_type=EventType.RIPPLE, freq_range=(80, 200),
                threshold_std=4.0, min_duration=0.025, cooldown=0.15, warmup_chunks=15,
            ),
        ],
        config=PipelineConfig(sample_rate=fs, n_channels=4, chunk_duration=0.2),
    ).run_offline()

    print(f"  Detected {len(events)} events")
    burst = [e for e in events if 6.8 < e.timestamp < 7.5 and e.channel_id == 0]
    print(f"  Burst hits on ch=0: {len(burst)}")
    print(f"  {'PASS' if burst else 'FAIL'}\n")
    return bool(burst)


# ============================================================
# 2. Live test
# ============================================================

def make_source(kind, inst_addr="", client_addr="0.0.0.0"):
    from dnb import NPlaySource, CerebusSource
    if kind == "cerebus":
        return CerebusSource(inst_addr=inst_addr, client_addr=client_addr)
    return NPlaySource()


def detect_source(inst_addr="", client_addr="0.0.0.0"):
    """Probe NPlay then Cerebus. Returns (kind, n_channels) or (None, 0)."""
    try:
        import pycbsdk
    except ImportError:
        print("  pycbsdk not installed — pip install direct-neural-biasing[live]")
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
                print(f"  {kind}: data flowing ({chunk.n_channels} channels)")
                return kind, chunk.n_channels
            else:
                print(f"  {kind}: connected, no data")
        except Exception as e:
            print(f"  {kind}: {e}")

    return None, 0


def run_live_test(kind, n_channels, run_seconds, channel, inst_addr, client_addr):
    ch_used = channel if channel is not None else 0
    print(f"\n{'=' * 60}")
    print(f"LIVE TEST — {kind} (ch={ch_used}, {run_seconds}s)")
    print("=" * 60)

    det_channels = [ch_used]

    config = PipelineConfig(
        sample_rate=30000,
        n_channels=n_channels,
        chunk_duration=0.2,
    )

    # Slow wave detection (0.5–4 Hz)
    wc = WaveletConvolution(
        freq_min=0.5, freq_max=30, n_freqs=10,
        channels=det_channels,
    )
    det = EventDetector(
        event_type=EventType.SHARP_WAVE,
        freq_range=(0.5, 4.0),
        threshold_std=2.0,
        min_duration=0.1,
        cooldown=0.5,
        warmup_chunks=10,
        channels=det_channels,
    )

    source = make_source(kind, inst_addr, client_addr)

    pipeline = Pipeline(
        source=source,
        modules=[wc, PowerEstimator(), det],
        config=config,
    )

    events = []
    latencies = []  # wall-clock time per chunk (source read + processing)
    chunk_count = [0]

    def on_event(event):
        events.append(event)
        if len(events) <= 20:
            print(
                f"  EVENT [{len(events):3d}] {event.event_type.name} "
                f"ch={event.channel_id} t={event.timestamp:.3f}s "
                f"dur={event.duration:.3f}s"
            )

    pipeline.on_event(None, on_event)

    # Instrument _process_chunk for diagnostics + latency
    original_process = pipeline._process_chunk

    def instrumented_process(chunk):
        t0 = time.perf_counter()
        result = original_process(chunk)
        dt = (time.perf_counter() - t0) * 1000  # ms
        latencies.append(dt)

        i = chunk_count[0]
        chunk_count[0] += 1

        band_amp = 0.0
        if result.wavelet is not None:
            w = result.wavelet
            bmask = (w.frequencies >= 0.5) & (w.frequencies <= 4.0)
            if np.any(bmask):
                band_amp = float(np.mean(w.amplitude[:, bmask, :]))

        warmup_done = det._chunks_seen > det._warmup_chunks
        rmean = float(np.mean(det._running_mean)) if det._running_mean is not None else 0
        rstd = float(np.mean(np.sqrt(det._running_var))) if det._running_var is not None else 0
        thresh = rmean + det._threshold_std * rstd

        # Print first 5, then every 25th
        if i < 5 or i % 25 == 0:
            label = "LIVE" if warmup_done else "WARM"
            print(
                f"  chunk {i:4d}: "
                f"sw_amp={band_amp:.3f} "
                f"thresh={thresh:.3f} "
                f"[{label}] "
                f"ev={len(result.events):2d} "
                f"latency={dt:.1f}ms"
            )
        return result

    pipeline._process_chunk = instrumented_process

    print(f"\n  Running for {run_seconds}s...\n")

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

    # ── Summary ──
    print(f"\n{'─' * 60}")
    print("SUMMARY")
    print(f"{'─' * 60}")
    print(f"  Wall time:        {t_wall:.1f}s")
    print(f"  Chunks processed: {chunk_count[0]}")
    print(f"  Events detected:  {len(events)}")

    if latencies:
        lat = np.array(latencies)
        print(f"\n  Processing latency per chunk:")
        print(f"    mean   = {np.mean(lat):6.1f} ms")
        print(f"    median = {np.median(lat):6.1f} ms")
        print(f"    p95    = {np.percentile(lat, 95):6.1f} ms")
        print(f"    p99    = {np.percentile(lat, 99):6.1f} ms")
        print(f"    max    = {np.max(lat):6.1f} ms")
        chunk_budget = config.chunk_duration * 1000
        overruns = np.sum(lat > chunk_budget)
        print(f"    budget = {chunk_budget:.0f} ms/chunk, overruns = {overruns}/{len(lat)}")

    if events:
        channels = sorted({e.channel_id for e in events})
        print(f"\n  Active channels: {channels}")
        durations = [e.duration for e in events]
        print(f"  Duration: min={min(durations):.3f}s  max={max(durations):.3f}s")
    else:
        print(f"\n  No events — data may not contain ripple-band transients at this threshold")

    return len(events)


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DNB smoke test")
    parser.add_argument("--live", choices=["nplay", "cerebus"], default=None,
                        help="Force a specific live source (skips auto-detect)")
    parser.add_argument("--no-live", action="store_true", help="Skip live test")
    parser.add_argument("--inst-addr", default="", help="NSP IP for Cerebus")
    parser.add_argument("--channels", type=int, default=83, help="Number of channels")
    parser.add_argument("--channel", type=int, default=None,
                        help="Single channel to process (default: all)")
    parser.add_argument("--seconds", type=int, default=10, help="Live test duration")
    args = parser.parse_args()

    run_offline_test()

    if args.no_live:
        print("(Skipping live test)")
    elif args.live:
        # Forced source — skip auto-detect
        run_live_test(
            kind=args.live,
            n_channels=args.channels,
            run_seconds=args.seconds,
            channel=args.channel,
            inst_addr=args.inst_addr,
            client_addr="0.0.0.0",
        )
    else:
        # Auto-detect
        print("Auto-detecting live source...")
        kind, n_ch = detect_source(inst_addr=args.inst_addr)
        if kind:
            run_live_test(
                kind=kind,
                n_channels=n_ch,
                run_seconds=args.seconds,
                channel=args.channel,
                inst_addr=args.inst_addr,
                client_addr="0.0.0.0",
            )
        else:
            print("  No live source found — skipping")