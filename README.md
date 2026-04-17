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

Installs numpy, scipy, pyyaml and makes `import dnb` work.

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

Single-channel pipeline. One hardware channel is selected at the source;
all processing is 1D.

```
Source → [Downsampler] → RingBuffer → WaveletConvolution → Detectors → StimTrigger → [Audio]
```

One shared ring buffer at the analysis rate. The downsampler transforms
the chunk, the pipeline writes it into the buffer, the wavelet reads a
sliding window from the buffer. No internal delays, no flush logic.

&nbsp;

| Module               | Role                                                                |
| -------------------- | ------------------------------------------------------------------- |
| `Downsampler`        | Decimate hardware rate (30 kHz) to analysis rate (500 Hz)           |
| `WaveletConvolution` | Sliding-window Morlet convolution → amplitude + phase               |
| `TargetWaveDetector` | **Activation** — crossing-based phase detection with z-score gating |
| `AmplitudeMonitor`   | **Inhibition** — broadband power monitor for IED rejection          |
| `StimTrigger`        | Phase-prediction scheduling, emits stims at exact predicted times   |

&nbsp;

### Phase-prediction scheduling

**Detection and stimulation happen at different phases.**

```
Detect at detection_phase  →  predict time to stim_phase  →  emit stim
```

Detect the slow wave at one phase (e.g. the trough, π) and stimulate at
another (e.g. the positive peak, 0). The trigger uses the detected frequency
to compute when `stim_phase` will occur and emits STIM events with exact
predicted timestamps.

Phase map: `0=peak  π/2=falling  π=trough  3π/2=rising  2π=peak`

Default config: `detection_phase=π` (trough), `stim_phase=0` (peak).
Lead time at 1 Hz is half a period = 500 ms.

&nbsp;

### Event semantics

- **`SLOW_WAVE`** — detection at `detection_phase`. Carries `frequency`,
  `amplitude`, `delay_to_stim_ms` in metadata.
- **`STIM`** — stimulation at predicted `stim_phase`. `pulse_index` is
  1-indexed. Timestamp is the exact predicted time.

&nbsp;

### N-pulse stimulation

| `n_pulses` | Behaviour                                                     |
| ---------- | ------------------------------------------------------------- |
| `0`        | Detection only — `SLOW_WAVE` events, no `STIM`                |
| `1`        | `SLOW_WAVE` + 1 `STIM` at next predicted `stim_phase`         |
| `3`        | `SLOW_WAVE` + `STIM` at next `stim_phase`, +2 at `+1/f, +2/f` |

All stim events are emitted immediately with their exact predicted
timestamps. In live mode, `StimScheduler` fires audio at those times
with sub-millisecond precision.

&nbsp;

---

&nbsp;

## Running on existing data

### Quick start — single file

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
        Downsampler(target_rate=500.0),

        WaveletConvolution(
            freq_min=0.5, freq_max=4.0,
            n_freqs=10, n_cycles_base=1.5,
        ),

        TargetWaveDetector(
            id="slow_wave",
            freq_range=(0.5, 4.0),
            detection_phase=pi,
            phase_tolerance=0.5,
            z_score_threshold=1.0,
        ),

        AmplitudeMonitor(
            id="ied_monitor",
            freq_range=(80.0, 120.0),
            adaptive_n_std=3.0,
        ),

        StimTrigger(
            activation_detector_id="slow_wave",
            inhibition_detector_id="ied_monitor",
            detection_phase=pi,
            stim_phase=0.0,
            n_pulses=1,
            backoff_s=5.0,
        ),
    ],
    config=PipelineConfig(sample_rate=30000, channel_id=0, chunk_duration=0.5),
)

events = pipeline.run_offline()
detections = [e for e in events if e.event_type == EventType.SLOW_WAVE]
stims = [e for e in events if e.event_type == EventType.STIM]
```

&nbsp;

### From config file

```python
from dnb.config import build_pipeline

pipeline = build_pipeline("config.yaml")
events = pipeline.run_offline()
```

&nbsp;

### From command line

```bash
python run.py --config config.yaml --offline
python run.py --config config.yaml --offline --detect-only   # n_pulses=0
python run.py --config config.yaml --offline --channel 5     # specific hardware channel
```

&nbsp;

### Batch processing

The notebook `tests/batch-processing.ipynb` processes all `.npz` files
in a directory and produces a summary report:

```python
from pathlib import Path
from dnb.config import build_pipeline_config, build_modules, load_config
from dnb import Pipeline, FileSource

cfg = load_config("config.yaml")
data_dir = Path("data/recordings")

for npz_path in sorted(data_dir.glob("*.npz")):
    pipeline = Pipeline(
        source=FileSource(npz_path),
        modules=build_modules(cfg),
        config=build_pipeline_config(cfg),
    )
    events = pipeline.run_offline()
    # ... analyse events
```

&nbsp;

### File format

`.npz` with keys:

- `continuous` — shape `(n_channels, n_samples)` or `(n_samples,)`
- `sample_rate` — scalar

Optional: `channel_ids`, `timestamps`.

The pipeline extracts one channel via `PipelineConfig.channel_id`
(default 0). All processing is single-channel.

&nbsp;

---

&nbsp;

## Offline validation

The notebook `tests/offline-smoke-tests.ipynb` provides interactive validation.
All parameters are defined in a single `CFG` dict at the top that mirrors
`config.yaml`.

1. **Clean sine** — verify phase detection and stim timing on a known waveform
2. **Synthetic SWs** — planted slow waves in pink noise, validate against ground truth
3. **N-pulse stim** — test n=0, n=1, n=3 modes, verify stim timing
4. **IED inhibition** — compare stim counts with / without `AmplitudeMonitor`
5. **Detection report** — stim-triggered average, phase distribution, inhibition summary

&nbsp;

---

&nbsp;

## Modules

### Downsampler

Decimates from hardware rate (e.g. 30 kHz) to analysis rate (e.g. 500 Hz)
using `scipy.signal.decimate`. Transforms the chunk only — the pipeline
handles all ring buffer writes.

&nbsp;

### WaveletConvolution

Complex Morlet wavelets with log-spaced centre frequencies and 1/f-scaled
cycle counts. Sliding-window convolution from the shared ring buffer.

On each chunk: reads `kernel_half_len + chunk_size` samples from the
ring buffer, convolves with the wavelet bank, extracts the chunk-sized
output. No internal delay, no flush needed.

Auto-detects actual sample rate from incoming chunks (handles upstream
downsampler transparently).

`n_cycles_base` controls the time-frequency tradeoff. Lower values (1.0–1.5)
give shorter kernels and faster settling, better suited to real-time use.

&nbsp;

### TargetWaveDetector

Crossing-based phase detector for a target frequency band. Finds where
the wavelet phase crosses `detection_phase` within each chunk, with
wrap-artifact rejection to distinguish real crossings from 2π boundary
effects.

Amplitude gating uses a rolling z-score (Welford's algorithm). Set
`z_score_threshold=1.0` for adaptive gating, or `amp_min=X` for fixed
thresholds.

&nbsp;

### AmplitudeMonitor

Broadband power monitor for IED detection. Bandpass filter is built
lazily from the actual chunk sample rate (not the hardware rate),
so it works correctly with or without a Downsampler upstream.

Adaptive mode uses a rolling z-score baseline. Active chunks are
excluded from the baseline to prevent drift.

&nbsp;

### StimTrigger

Phase-prediction scheduling. On detection at `detection_phase`:

```
Δφ = (stim_phase - detection_phase) mod 2π
Δt = Δφ / (2π × f)
```

Uses the **target** `detection_phase` for delay calculation, not the
noisy measured phase. All stim events are emitted immediately with
exact predicted timestamps.

Pulse k (1-indexed) fires at `t_detection + Δt + (k-1)/f`.

&nbsp;

### AudioStimulator / StimScheduler

`AudioStimulator` — plays a WAV file on `STIM` events (offline/testing).

`StimScheduler` — daemon thread with high-precision sleep for live
operation. Receives `STIM` events, sleeps until their exact timestamps,
fires audio with sub-millisecond jitter.

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
│   ├── offline-smoke-tests.ipynb
│   └── test_data.py
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
