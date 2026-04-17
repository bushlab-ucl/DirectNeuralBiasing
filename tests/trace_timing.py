"""Diagnostic: trace chunk boundaries, wavelet settling, and stim timing.

Run from the repo root:
    python tests/trace_timing.py

This shows exactly what happens at each chunk boundary.
"""

import sys
sys.path.insert(0, '.')

import numpy as np
from math import pi
from dnb import Pipeline, FileSource, PipelineConfig, EventType
from dnb.modules import (
    WaveletConvolution, TargetWaveDetector, StimTrigger, Downsampler,
)
from dnb.modules.base import ProcessResult
from dnb.validation.synthetic import save_synthetic

# ── Generate a clean 1 Hz sine at 30 kHz ─────────────────────
HARDWARE_RATE = 30000.0
ANALYSIS_RATE = 500.0
DS_FACTOR = int(HARDWARE_RATE / ANALYSIS_RATE)
DURATION = 10.0  # short, just for tracing

n = int(DURATION * HARDWARE_RATE)
t = np.arange(n) / HARDWARE_RATE
signal = 500.0 * np.sin(2 * pi * 1.0 * t).reshape(1, -1)
path = "/tmp/trace_sine.npz"
save_synthetic(path, signal, HARDWARE_RATE)

print("=" * 70)
print("TIMING TRACE")
print("=" * 70)

for chunk_dur in [0.5, 0.1]:
    print(f"\n{'─' * 70}")
    print(f"chunk_duration = {chunk_dur}s")
    print(f"  chunk_samples at {HARDWARE_RATE:.0f} Hz = {int(chunk_dur * HARDWARE_RATE)}")
    print(f"  chunk_samples at {ANALYSIS_RATE:.0f} Hz = {int(chunk_dur * ANALYSIS_RATE)}")
    print(f"{'─' * 70}")

    # Build pipeline manually to intercept
    config = PipelineConfig(
        sample_rate=HARDWARE_RATE, n_channels=1,
        buffer_duration=10.0, chunk_duration=chunk_dur,
    )

    ds = Downsampler(target_rate=ANALYSIS_RATE)
    wav = WaveletConvolution(freq_min=0.5, freq_max=4.0, n_freqs=10, n_cycles_base=1.0)
    det = TargetWaveDetector(
        id="slow_wave", freq_range=(0.5, 4.0),
        detection_phase=pi, phase_tolerance=0.1,
        z_score_threshold=0.0,  # accept everything for clean sine
        warmup_chunks=0,  # no warmup for this trace
    )
    trig = StimTrigger(
        activation_detector_id="slow_wave",
        inhibition_detector_id=None,
        n_pulses=1, stim_phase=0.0,
        backoff_s=0.0,  # detect every cycle
        inhibition_cooldown_s=0.0,
    )

    pipeline = Pipeline(
        source=FileSource(path),
        modules=[ds, wav, det, trig],
        config=config,
    )

    # Run and collect events
    events = pipeline.run_offline()
    detections = [e for e in events if e.event_type == EventType.SLOW_WAVE]
    stims = [e for e in events if e.event_type == EventType.STIM]

    print(f"\n  Results: {len(detections)} detections, {len(stims)} stims")

    if detections:
        det_times = [e.timestamp for e in detections]
        print(f"  Detection times: {[f'{t:.3f}' for t in det_times[:10]]}")

    if stims:
        stim_times = [e.timestamp for e in stims]
        print(f"  Stim times:      {[f'{t:.3f}' for t in stim_times[:10]]}")

        # Check stim phase accuracy
        sig_ds = signal[0, ::DS_FACTOR]
        for s in stims[:5]:
            idx = int(s.timestamp * ANALYSIS_RATE)
            if 0 <= idx < len(sig_ds):
                val = sig_ds[idx]
                # For sin wave: peak is at +500, trough at -500
                phase_at_stim = np.arcsin(np.clip(val / 500.0, -1, 1))
                print(f"    stim t={s.timestamp:.3f}s  signal={val:.0f}  "
                      f"(peak=+500, should be near peak)")

    # Check wavelet info
    print(f"\n  Wavelet kernel half-len: {wav.max_kernel_half_len} samples")
    if wav._sample_rate > 0:
        print(f"  Wavelet built for rate: {wav._sample_rate:.0f} Hz")
        print(f"  Kernel half-len in sec: {wav.max_kernel_half_len / wav._sample_rate:.3f}s")
        ds_chunk = int(chunk_dur * ANALYSIS_RATE)
        chunks_to_settle = wav.max_kernel_half_len / ds_chunk
        print(f"  Chunks needed for back overlap: ~{chunks_to_settle:.1f}")
        print(f"  = ~{chunks_to_settle * chunk_dur:.1f}s before first valid output")

print("\n" + "=" * 70)
print("KEY INSIGHT: The wavelet outputs results for chunk N-1 when chunk N")
print("arrives. Stim events fire when chunk_time >= scheduled_time.")
print("So stim timing = detection_time + phase_delay, BUT the detection")
print("itself is delayed by 1 chunk, AND the stim can only fire at the")
print("NEXT chunk boundary after its scheduled time.")
print("")
print("Total worst-case delay = wavelet_delay + chunk_quantisation")
print(f"  At chunk=0.5s: 0.5 + 0.5 = 1.0s extra")
print(f"  At chunk=0.1s: 0.1 + 0.1 = 0.2s extra")
print("=" * 70)