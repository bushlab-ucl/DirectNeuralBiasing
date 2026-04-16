# direct-neural-biasing

Low-latency closed-loop neural signal processing for Blackrock Cerebus devices.

Developed by the [Human Electrophysiology Lab](https://bushlab-ucl.github.io) at UCL.

**PyPI** · [direct-neural-biasing](https://pypi.org/project/direct-neural-biasing/)  
**CereLink SDK** · [GitHub](https://github.com/CerebusOSS/CereLink) · [Wiki](https://github.com/CerebusOSS/CereLink/wiki)  
**pycbsdk** · [GitHub](https://github.com/CerebusOSS/pycbsdk)

&nbsp;

---

&nbsp;

## Install

```bash
git clone https://github.com/bushlab-ucl/DirectNeuralBiasing
cd DirectNeuralBiasing
pip install -e .
```

That's it. Installs numpy, scipy, pyyaml and makes `import dnb` work.

For development (adds matplotlib + jupyter):

```bash
pip install -e ".[dev]"
```

For live hardware (adds pycbsdk):

```bash
pip install -e ".[live]"
```

&nbsp;

### Hospital machine setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev,live]"
```

No build tools needed beyond pip.
No requirements.txt — everything is declared in `pyproject.toml`.

&nbsp;

---

&nbsp;

## Architecture

The pipeline follows a **Filter → Detector → Trigger** pattern:

```
Source → [Downsampler] → WaveletConvolution → Detectors → StimTrigger → [Audio]
```

&nbsp;

| Module               | Role                                                                  |
| -------------------- | --------------------------------------------------------------------- |
| `Downsampler`        | Decimate hardware rate (30 kHz) to analysis rate (500 Hz)             |
| `WaveletConvolution` | Decompose signal into amplitude + phase at all frequencies            |
| `TargetWaveDetector` | **Activation** — "phase is at detection target in this band"          |
| `AmplitudeMonitor`   | **Inhibition** — "broadband power too high, block stim"               |
| `StimTrigger`        | Combine activation + inhibition, schedule n-pulse stim at stim target |

&nbsp;

### Phase-prediction scheduling

The key conceptual point: **detection and stimulation happen at different phases.**

```
Detect at detection_phase  →  predict time to stim_phase  →  schedule stim
```

You detect the slow wave at one phase (e.g. the trough, π) and stimulate at
another (e.g. the positive peak, 0). The trigger uses the detected frequency
to compute when `stim_phase` will occur and schedules the audio pulse for
that future time — giving you lead time to fire the stim accurately at the
target phase, regardless of chunk boundaries.

Phase map: `0=peak  π/2=falling  π=trough  3π/2=rising  2π=peak`

Default config: `detection_phase=π` (trough), `stim_phase=0` (peak).
Lead time at 1 Hz is half a period = 500 ms.

&nbsp;

### Event semantics

The pipeline emits two event types:

- **`SLOW_WAVE`** — a detection at `detection_phase`. Logged always.
  Carries `detection_phase`, `frequency`, `amplitude`, and `delay_to_stim_ms`
  in metadata. Does not trigger audio.
- **`STIM`** — a scheduled stimulation at a predicted future `stim_phase`.
  `pulse_index` is 1-indexed. These trigger the `AudioStimulator`.

&nbsp;

### N-pulse stimulation

The `StimTrigger` supports configurable n-pulse stimulation. All pulses are
scheduled at predicted future occurrences of `stim_phase`:

| `n_pulses` | Behaviour                                                                           |
| ---------- | ----------------------------------------------------------------------------------- |
| `0`        | Detection only — emit `SLOW_WAVE`, no `STIM` events                                 |
| `1`        | Emit `SLOW_WAVE` + 1 `STIM` scheduled for the next `stim_phase` occurrence          |
| `3`        | Emit `SLOW_WAVE` + `STIM` at next `stim_phase`, then 2 more at `+1/freq`, `+2/freq` |

Detectors set flags on `ProcessResult.detections`.
The `StimTrigger` reads those flags to decide whether to fire.

This separation means you can swap detectors, add inhibition criteria,
or change cooldowns — without touching detection logic.

&nbsp;

---

&nbsp;

## Quick start

```python
from math import pi
from dnb import Pipeline, FileSource, PipelineConfig, EventType
from dnb.modules import (
    WaveletConvolution, TargetWaveDetector, AmplitudeMonitor, StimTrigger,
    Downsampler,
)

pipeline = Pipeline(
    source=FileSource("recording.npz"),
    modules=[
        Downsampler(target_rate=500.0),          # omit if data is already at analysis rate

        WaveletConvolution(
            freq_min=0.5, freq_max=4.0,
            n_freqs=10, n_cycles_base=1.5,
        ),

        TargetWaveDetector(
            id="slow_wave",
            freq_range=(0.5, 4.0),
            detection_phase=pi,                  # π = trough (where we detect)
            phase_tolerance=0.05,
            amp_min=1000.0,
        ),

        AmplitudeMonitor(
            id="ied_monitor",
            freq_range=(80.0, 120.0),            # broadband IED power check
            adaptive_n_std=3.0,
        ),

        StimTrigger(
            activation_detector_id="slow_wave",
            inhibition_detector_id="ied_monitor",
            n_pulses=1,
            stim_phase=0.0,                      # 0 = peak (where we stimulate)
            backoff_s=5.0,
        ),
    ],
    config=PipelineConfig(sample_rate=30000, n_channels=1, chunk_duration=0.5),
)

events = pipeline.run_offline()

# Detections and stims are separate event types
detections = [e for e in events if e.event_type == EventType.SLOW_WAVE]
stims = [e for e in events if e.event_type == EventType.STIM]
```

&nbsp;

### From config file

```python
from dnb.config import build_pipeline

pipeline = build_pipeline("config.yaml")
pipeline.run_online()
```

&nbsp;

### From command line

```bash
python run.py --config config.yaml --offline
python run.py --config config.yaml --detect-only   # n_pulses=0
```

&nbsp;

---

&nbsp;

## Offline validation

The notebook `tests/offline-smoke-tests.ipynb` provides interactive validation.
All parameters are defined in a single `CFG` dict at the top of the notebook
that mirrors `config.yaml`, so tests exercise the same pipeline path that
runs at the hospital (including the downsampler, at 30 kHz → 500 Hz).

1. **Clean sine** — verify phase detection on a known waveform
2. **Synthetic SWs** — planted slow waves in pink noise, validate against ground truth
3. **N-pulse stim** — test n=0, n=1, n=3 modes, verify scheduled pulse timing
4. **IED inhibition** — compare stim counts with / without `AmplitudeMonitor`
5. **Detection report** — stim-triggered average, phase distribution, inhibition summary
6. **Timing precision** — verify detection→stim delay matches phase prediction

&nbsp;

---

&nbsp;

## Modules

### Downsampler

Decimates from hardware rate (30 kHz) to analysis rate (500 Hz) using
a Butterworth IIR filter. Maintains its own ring buffer at the downsampled
rate, which replaces the pipeline's ring buffer for downstream modules.

Recommended for all pipelines — including offline synthetic tests — so
that the tested path matches the live path. Skip it only when input data
is already at the analysis rate.

&nbsp;

### WaveletConvolution

Complex Morlet wavelets with log-spaced centre frequencies and 1/f-scaled
cycle counts. Single-pass replacement for traditional bandpass filter banks.

**Symmetric overlap-save**: the wavelet maintains an internal one-chunk
delay so that each output chunk gets both past and future context from the
ring buffer. Output for chunk N is produced when chunk N+1 arrives. This
adds `chunk_duration` of latency (well within the phase-prediction lead
time) but eliminates the chunk-boundary phase bias that arises from having
only past context.

**Auto-rate-detection**: kernels are built on the first chunk received,
using the chunk's actual sample rate. This means the wavelet works
correctly whether there's a Downsampler upstream or not — no need to
manually pass the post-downsample rate.

Sets `wavelet_settled=True` on `ProcessResult` once enough history is
available on both sides for clean symmetric overlap. Downstream detectors
skip unsettled chunks (including the first chunk, where no previous chunk
has been stashed yet).

`n_cycles_base` controls the time-frequency tradeoff. Lower values (1.0–1.5)
give shorter kernels and faster settling, better suited to real-time use.
Higher values give better frequency resolution at the cost of longer kernels.

&nbsp;

### TargetWaveDetector

Monitors instantaneous phase in a target frequency band.
Configurable for any oscillation — set `freq_range=(0.5, 2.0)` for slow waves,
`(4, 8)` for theta, etc.

Emits candidates whenever the instantaneous phase matches `detection_phase`
(within `phase_tolerance` radians) and amplitude is within `[amp_min, amp_max]`.
Amplitude is instantaneous (per chunk) — the wavelet's Gaussian envelope
already provides temporal smoothing.

Each candidate carries `phase`, `frequency`, `amplitude`, and `timestamp`
for the StimTrigger to compute phase-prediction scheduling.

&nbsp;

### AmplitudeMonitor

Broadband power monitor for IED detection. Bandpasses the raw signal
(default 80–120 Hz) with a Butterworth filter, computes RMS power, and
flags chunks where power exceeds threshold.

Operates independently of the wavelet decomposition — IEDs are broadband
events best caught with a straightforward power check.

Supports absolute threshold mode and adaptive mode (mean + n·σ of recent history).

&nbsp;

### StimTrigger

Reads an activation detector and optional inhibition detector.
On detection, emits a `SLOW_WAVE` event and schedules `n_pulses` `STIM`
events at predicted future occurrences of `stim_phase`.

Given detection at phase φ_det with frequency f, the delay to the next
`stim_phase` (φ_stim) is:

```
Δφ = (φ_stim - φ_det) mod 2π
Δt = Δφ / (2π × f)
```

Pulse k (1-indexed) fires at `t_detection + Δt + (k-1)/f`.

Inhibition cancels all pending scheduled stims and starts a cooldown period.

&nbsp;

### AudioStimulator

Plays a WAV file on `STIM` events for closed-loop auditory stimulation.

For live operation, use `StimScheduler` instead — it runs in a daemon thread
and uses high-precision sleep to fire audio with sub-chunk timing jitter.

&nbsp;

---

&nbsp;

## Chunk duration and latency

The pipeline processes data in chunks. Small chunks give low latency but
more FFT overhead. For the wavelet, the longest kernel is at `freq_min`
with half-length `4σ = 4 × n_cycles_base / (2π × freq_min)`.

At `freq_min=0.5 Hz` with `n_cycles_base=1.5`, kernel half-length is ~1.9s.
At 500 Hz analysis rate this is ~955 samples — well within the 10s
default ring buffer.

The wavelet requires full symmetric overlap on both sides before reporting
`wavelet_settled=True`. With `chunk_duration=0.5s`, settling requires
approximately `kernel_half_len / chunk_samples` chunks of back overlap
(roughly 4 chunks = 2s at the default config) plus one chunk of forward
overlap (0.5s). Detectors skip unsettled chunks.

For n-pulse stimulation, chunk boundaries mostly don't matter for timing:
once the slow wave is detected, stim times are predicted analytically
(`t₀ + Δt + k/freq`). The stim events fire as soon as chunk time passes
their scheduled timestamp, so offline timing precision is quantised to
`chunk_duration`. In live mode, `StimScheduler` achieves sub-chunk precision
with a high-priority scheduling thread.

&nbsp;

---

&nbsp;

## Data sources

| Source          | Class           | Install                    |
| --------------- | --------------- | -------------------------- |
| Saved .npz file | `FileSource`    | —                          |
| NPlay simulator | `NPlaySource`   | `pip install -e ".[live]"` |
| Cerebus NSP     | `CerebusSource` | `pip install -e ".[live]"` |

&nbsp;

## File format

`.npz` with keys:

- `continuous` — shape `(n_channels, n_samples)`
- `sample_rate` — scalar

Optional: `channel_ids`, `timestamps`.

&nbsp;

---

&nbsp;

## Repo structure

```
DirectNeuralBiasing/
│
├── dnb/                      the library
│   ├── core/                 types, ring buffer
│   ├── engine/               pipeline, event bus
│   ├── modules/              wavelet, detectors, trigger, audio
│   ├── sources/              file, live (NPlay / Cerebus)
│   └── validation/           synthetic data, ground truth matching
│
├── tests/
│   └── offline-smoke-tests.ipynb
│
├── assets/
│   └── pink_noise_short.wav
│
├── config.yaml
├── run.py
├── pyproject.toml
├── README.md
└── LICENSE
```

&nbsp;

---

&nbsp;

## License

CC-BY-NC-4.0
