# direct-neural-biasing

Low-latency closed-loop neural signal processing for Blackrock Cerebus devices.

Developed by the [Human Electrophysiology Lab](https://bushlab-ucl.github.io) at UCL.

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

&nbsp;

### Hospital machine setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev,live]"
```

No build tools needed beyond pip.
Everything is declared in `pyproject.toml`.

&nbsp;

---

&nbsp;

## Architecture

Single-channel pipeline. One hardware channel is selected at the source;
all processing is 1D.

```
Source → Downsampler → RingBuffer → WaveletConvolution → Detectors → StimTrigger → [Audio]
```

One shared ring buffer at the analysis rate (500 Hz). The downsampler
transforms the chunk, the pipeline writes it into the buffer, the wavelet
reads a sliding window from the buffer. No internal delays, no flush logic.

&nbsp;

| Module               | Role                                                                |
| -------------------- | ------------------------------------------------------------------- |
| `Downsampler`        | Decimate hardware rate (30 kHz) to analysis rate (500 Hz)           |
| `WaveletConvolution` | Sliding-window Morlet convolution → amplitude + phase               |
| `TargetWaveDetector` | **Activation** — crossing-based phase detection with z-score gating |
| `AmplitudeMonitor`   | **Inhibition** — broadband power monitor for IED rejection          |
| `StimTrigger`        | Phase-prediction scheduling, emits stims at exact predicted times   |

&nbsp;

### How it works

**Detection and stimulation happen at different phases.**

Detect the slow wave at the trough (π) and stimulate at the positive
peak (0). The trigger uses the detected frequency to compute when
the peak will occur and emits a STIM event with the exact predicted
timestamp.

```
Detect at trough (π)  →  predict 500ms to peak (0)  →  schedule stim
```

Phase map: `0=peak  π/2=falling  π=trough  3π/2=rising  2π=peak`

Default config: `detection_phase=π`, `stim_phase=0`.
At 1 Hz, the lead time is half a period = 500 ms.

&nbsp;

### Events

- **`SLOW_WAVE`** — detection at `detection_phase`. Metadata:
  `frequency`, `amplitude`, `delay_to_stim_ms`.
- **`STIM`** — stimulation at predicted `stim_phase`. Metadata:
  `pulse_index` (1-indexed), `frequency`, `detection_time`.

&nbsp;

### N-pulse stimulation

| `n_pulses` | Behaviour                                        |
| ---------- | ------------------------------------------------ |
| `0`        | Detection only — `SLOW_WAVE` events, no `STIM`   |
| `1`        | `SLOW_WAVE` + 1 `STIM` at next predicted peak    |
| `3`        | `SLOW_WAVE` + 3 `STIM` at next 3 predicted peaks |

All stim events are emitted immediately with their exact predicted
timestamps. In live mode, `StimScheduler` fires audio at those times.

&nbsp;

---

&nbsp;

## Data format

### Blackrock .ns6

The native recording format. Convert to `.npz` for offline processing:

```bash
python ns6_to_npz.py recording.ns6
python ns6_to_npz.py recording.ns6 --uv    # store as float32 µV
```

### .npz (ns6-converted)

Produced by `ns6_to_npz.py`. `FileSource` reads this automatically.

- `data` — `(n_samples, n_channels)` int16
- `fs` — sample rate (Hz), scalar
- `scale_factors` — `(n_channels,)` float64, multiply int16 → µV
- `electrode_ids` — `(n_channels,)` int32
- `labels` — `(n_channels,)` str

### .npz (synthetic)

Produced by the validation tools. Also read automatically by `FileSource`.

- `continuous` — `(n_channels, n_samples)` or `(n_samples,)` float64
- `sample_rate` — scalar

The pipeline extracts one channel via `PipelineConfig.channel_id`
(default 0).

&nbsp;

---

&nbsp;

## Offline validation

### Batch processing — real data

The notebook `validation/batch-processing.ipynb` processes a list of
`.npz` recordings. For each file it:

1. Runs the full pipeline (with and without IED inhibition)
2. Saves a `_detections.csv` with sample indices at the **original
   hardware rate** — for visual validation against the raw recording
3. Produces a 3-panel report figure (stim-triggered average, phase
   polar plot, fired vs blocked stim counts)
4. Optionally plots every individual detection with context

See `validation/README.md` for step-by-step instructions.

### Smoke tests — synthetic data

The notebook `tests/offline-smoke-tests.ipynb` validates the pipeline
on synthetic data:

1. **Clean sine** — phase detection and stim timing on a known waveform
2. **Synthetic SWs** — planted slow waves in pink noise, F1 score
3. **N-pulse** — n=0, n=1, n=3 modes
4. **IED inhibition** — stim counts with/without `AmplitudeMonitor`
5. **Detection report** — stim-triggered average, phase accuracy

&nbsp;

---

&nbsp;

## Running the pipeline

### From Python

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
        WaveletConvolution(freq_min=0.5, freq_max=4.0, n_freqs=20, n_cycles_base=1.0),
        TargetWaveDetector(
            id="slow_wave", freq_range=(0.5, 4.0),
            detection_phase=pi, phase_tolerance=0.05, z_score_threshold=1.0,
        ),
        AmplitudeMonitor(id="ied_monitor", freq_range=(80.0, 120.0), adaptive_n_std=5.0),
        StimTrigger(
            activation_detector_id="slow_wave", inhibition_detector_id="ied_monitor",
            detection_phase=pi, stim_phase=0.0, n_pulses=1, backoff_s=2.5,
        ),
    ],
    config=PipelineConfig(sample_rate=30000, channel_id=0, chunk_duration=0.1),
)

events = pipeline.run_offline()
detections = [e for e in events if e.event_type == EventType.SLOW_WAVE]
stims = [e for e in events if e.event_type == EventType.STIM]
```

### From config file

```python
from dnb.config import build_pipeline
pipeline = build_pipeline("config.yaml")
events = pipeline.run_offline()
```

### From command line

```bash
python run.py --config config.yaml --offline
python run.py --config config.yaml --offline --detect-only
python run.py --config config.yaml --offline --channel 5
```

&nbsp;

---

&nbsp;

## Modules

### Downsampler

Decimates from hardware rate to analysis rate using `scipy.signal.decimate`.
Transforms the chunk only — the pipeline handles all ring buffer writes.

### WaveletConvolution

Complex Morlet wavelets with log-spaced centre frequencies and 1/f-scaled
cycle counts. Sliding-window convolution from the shared ring buffer.
Auto-detects actual sample rate from incoming chunks.

`n_cycles_base` controls the time-frequency tradeoff. Lower = faster
settling (good for real-time). Higher = better frequency resolution.

### TargetWaveDetector

Crossing-based phase detector. Finds where the wavelet phase crosses
`detection_phase` within each chunk. Wrap-artifact rejection distinguishes
real crossings from 2π boundary effects.

Amplitude gating via rolling z-score (Welford's algorithm):
`z_score_threshold=1.0` for adaptive, `amp_min=X` for fixed.

### AmplitudeMonitor

Broadband power monitor for IED detection. Bandpass filter built lazily
from the actual chunk sample rate. Adaptive threshold via rolling z-score
baseline.

### StimTrigger

Phase-prediction scheduling. Uses the **target** `detection_phase` for
delay calculation (not the noisy measured phase). All stim events emitted
immediately with exact predicted timestamps.

`Δt = (stim_phase - detection_phase) mod 2π / (2π × f)`

### StimScheduler

Daemon thread for live operation. Receives STIM events, sleeps until
their exact timestamps, fires audio.

&nbsp;

---

&nbsp;

## Data sources

| Source          | Class           | Install                    |
| --------------- | --------------- | -------------------------- |
| .npz file       | `FileSource`    | —                          |
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
├── validation/
│   ├── batch-processing.ipynb
│   ├── ns6_to_npz.py
│   └── README.md             ← start here for offline processing
│
├── tests/
│   ├── offline-smoke-tests.ipynb
│   └── test_data.py
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
