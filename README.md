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

| Module               | Role                                                       |
| -------------------- | ---------------------------------------------------------- |
| `WaveletConvolution` | Decompose signal into amplitude + phase at all frequencies |
| `TargetWaveDetector` | **Activation** — "phase is at target in this band"         |
| `AmplitudeMonitor`   | **Inhibition** — "broadband power too high, block stim"    |
| `StimTrigger`        | Combine activation + inhibition, schedule n-pulse stim     |

&nbsp;

### Event semantics

The pipeline emits two event types:

- **`SLOW_WAVE`** — a detection. Logged, never triggers audio. Always emitted when the detector finds a candidate at the target phase with sufficient amplitude.
- **`STIM`** — an audio stimulation scheduled at a predicted future positive peak. `pulse_index` is 1-indexed. These trigger the `AudioStimulator`.

The detection itself is never a stimulation — it's the trigger for scheduling future stims. This matters because in closed-loop the detection happens mid-cycle; the stim needs to land on the next peak.

&nbsp;

### N-pulse stimulation

The `StimTrigger` supports configurable n-pulse stimulation:

| `n_pulses` | Behaviour                                                           |
| ---------- | ------------------------------------------------------------------- |
| `0`        | Detection only — emit `SLOW_WAVE`, no `STIM` events                 |
| `1`        | Detect, schedule 1 stim at next predicted peak: `t₀ + 1/freq`       |
| `3`        | Detect, schedule 3 stims at next 3 peaks: `t₀ + k/freq` for k=1,2,3 |

Once the slow wave frequency is known from the first detection, subsequent stim times are predictable — no need to re-detect.

&nbsp;

Detectors set flags on `ProcessResult.detections`.
The `StimTrigger` reads those flags to decide whether to fire.

This separation means you can swap detectors, add inhibition criteria,
or change cooldowns — without touching detection logic.

&nbsp;

---

&nbsp;

## Quick start

```python
from dnb import Pipeline, FileSource, PipelineConfig, EventType
from dnb.modules import (
    WaveletConvolution, TargetWaveDetector, AmplitudeMonitor, StimTrigger,
)

pipeline = Pipeline(
    source=FileSource("recording.npz"),
    modules=[
        WaveletConvolution(freq_min=0.5, freq_max=30, n_freqs=10),

        TargetWaveDetector(
            id="slow_wave",
            freq_range=(0.5, 2.0),
            target_phase=0.0,       # 0 = positive peak
            amp_min=50.0,
        ),

        AmplitudeMonitor(
            id="ied_monitor",
            freq_range=(80.0, 120.0),   # broadband IED power check
            adaptive_n_std=3.0,
        ),

        StimTrigger(
            activation_detector_id="slow_wave",
            inhibition_detector_id="ied_monitor",
            n_pulses=1,
            backoff_s=5.0,
        ),
    ],
    config=PipelineConfig(sample_rate=1000, n_channels=1, chunk_duration=0.5),
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
python run.py --config config.yaml --snr-sweep
```

&nbsp;

---

&nbsp;

## Offline validation

The notebook `tests/offline-smoke-tests.ipynb` provides interactive validation.
All parameters are defined in a single `CFG` dict at the top of the notebook
so nothing is redefined across cells.

1. **Clean sine** — verify phase detection on a known waveform
2. **Synthetic SWs** — planted slow waves in pink noise, validate against ground truth
3. **N-pulse stim** — test n=0, n=1, n=3 modes, verify scheduled pulse timing
4. **IED inhibition** — compare stim counts with / without AmplitudeMonitor
5. **N-pulse + inhibition** — verify that inhibition cancels pending scheduled stims
6. **SNR sweep** — precision / recall / F1 across noise levels
7. **Wavelet inspection** — visualise the time-frequency decomposition
8. **Parameter exploration** — sweep phase tolerance, backoff, etc.

&nbsp;

---

&nbsp;

## Modules

### WaveletConvolution

Complex Morlet wavelets with log-spaced frequencies and 1/f-scaled cycle counts.
Replaces traditional bandpass filter banks with a single-pass decomposition.
Uses overlap-save to eliminate chunk boundary artefacts.

Sets `wavelet_settled=True` on `ProcessResult` once enough history is available
for clean overlap-save. Downstream detectors skip unsettled chunks.

&nbsp;

### TargetWaveDetector

Monitors instantaneous phase in a target frequency band.
Configurable for any oscillation — set `freq_range=(0.5, 2.0)` for slow waves,
`(4, 8)` for theta, etc.
Outputs candidate events with phase, amplitude, and frequency metadata.

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
On detection, emits a `SLOW_WAVE` event and schedules `n_pulses` `STIM` events
at predicted future positive peaks based on the detected frequency.

Inhibition cancels all pending scheduled stims and starts a cooldown period.

&nbsp;

### Downsampler

Decimates from hardware rate (30 kHz) to analysis rate (500 Hz).
Only needed for live hardware — not for synthetic data.

&nbsp;

### AudioStimulator

Plays a WAV file on `STIM` events for closed-loop auditory stimulation.

&nbsp;

---

&nbsp;

## Chunk duration and latency

The pipeline processes data in chunks. With small chunks (e.g. 50 ms),
latency is low but you pay more FFT overhead — each chunk does a full
FFT of size `next_fast_len(chunk_samples + kernel_length)`.

For the wavelet, the longest kernel (0.5 Hz, 3 cycles) has a half-length
of ~3.8 s at 1 kHz. With 50 ms chunks, the overlap-save needs ~76 chunks
of history before `wavelet_settled` becomes `True`. The wavelet still
works before that — it just has edge artefacts at chunk boundaries.

For n-pulse stimulation this mostly doesn't matter: once the slow wave
is detected, stim times are predicted analytically (`t₀ + k/freq`).
The stim events fire as soon as chunk time passes their scheduled timestamp,
so timing precision is quantised to `chunk_duration`.

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
