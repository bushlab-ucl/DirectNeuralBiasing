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

The pipeline mirrors the Rust implementation's **Filter → Detector → Trigger** pattern:

```
Source → [Downsampler] → WaveletConvolution → Detectors → StimTrigger → [Audio]
```

&nbsp;

| Module               | Role                                                       | Rust equivalent     |
| -------------------- | ---------------------------------------------------------- | ------------------- |
| `WaveletConvolution` | Decompose signal into amplitude + phase at all frequencies | `BandPassFilter`    |
| `TargetWaveDetector` | **Activation** — "phase is at target in this band"         | `WavePeakDetector`  |
| `AmplitudeMonitor`   | **Inhibition** — "HF amplitude too high, block stim"       | `ThresholdDetector` |
| `StimTrigger`        | Combine activation + inhibition with cooldowns             | `PulseTrigger`      |

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
from math import pi
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
            target_phase=pi,
            amp_min=50.0,
        ),

        AmplitudeMonitor(
            id="ied_monitor",
            freq_range=(10.0, 40.0),
            ref_freq_range=(0.5, 2.0),
            ratio_max=0.5,
        ),

        StimTrigger(
            activation_detector_id="slow_wave",
            inhibition_detector_id="ied_monitor",
            backoff_s=5.0,
        ),
    ],
    config=PipelineConfig(sample_rate=1000, n_channels=1, chunk_duration=0.5),
)

events = pipeline.run_offline()
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

The notebook `tests/offline-smoke-tests.ipynb` provides interactive validation:

1. **Clean sine** — verify phase detection on a known waveform
2. **Synthetic SWs** — planted slow waves in pink noise, validate against ground truth
3. **IED inhibition** — compare stim counts with / without AmplitudeMonitor
4. **SNR sweep** — precision / recall / F1 across noise levels
5. **Wavelet inspection** — visualise the time-frequency decomposition
6. **Parameter exploration** — sweep phase tolerance, backoff, etc.

&nbsp;

---

&nbsp;

## Modules

### WaveletConvolution

Complex Morlet wavelets with log-spaced frequencies and 1/f-scaled cycle counts.
Replaces traditional bandpass filter banks with a single-pass decomposition.
Uses overlap-save to eliminate chunk boundary artefacts.

&nbsp;

### TargetWaveDetector

Monitors instantaneous phase in a target frequency band.
Configurable for any oscillation — set `freq_range=(0.5, 2.0)` for slow waves,
`(4, 8)` for theta, etc.
Outputs candidate events with phase, amplitude, and frequency metadata.

&nbsp;

### AmplitudeMonitor

Watches mean amplitude in a frequency band.
Supports absolute threshold mode and ratio mode (HF/LF ratio for IED rejection).

&nbsp;

### StimTrigger

Combines an activation detector and optional inhibition detector.
Applies per-channel backoff and inhibition cooldown.
Schedules STIM2 (paired pulse) after a configurable delay.

&nbsp;

### Downsampler

Decimates from hardware rate (30 kHz) to analysis rate (500 Hz).
Only needed for live hardware — not for synthetic data.

&nbsp;

### AudioStimulator

Plays a WAV file on STIM events for closed-loop auditory stimulation.

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
