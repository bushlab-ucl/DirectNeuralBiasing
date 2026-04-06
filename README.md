# direct-neural-biasing v3

Low-latency closed-loop neural signal processing for Blackrock Cerebus devices.

Developed by the [Human Electrophysiology Lab](https://bushlab-ucl.github.io) at UCL.

## Architecture

The pipeline mirrors the Rust implementation's **Filter → Detector → Trigger** pattern:

```
Source → [Downsampler] → WaveletConvolution → Detectors → StimTrigger → [Audio]
```

| Module | Role | Rust equivalent |
|---|---|---|
| `WaveletConvolution` | Decompose signal into amplitude + phase at all frequencies | `BandPassFilter` |
| `TargetWaveDetector` | **Activation** — "phase is at target in this band" | `WavePeakDetector` |
| `AmplitudeMonitor` | **Inhibition** — "HF amplitude too high, block stim" | `ThresholdDetector` |
| `StimTrigger` | Combine activation + inhibition with cooldowns, fire STIM1/STIM2 | `PulseTrigger` |

Detectors set flags on the `ProcessResult.detections` dict. The `StimTrigger` reads those flags to decide whether to fire. This separation means you can swap detectors, add new inhibition criteria, or change cooldowns without touching detection logic.

## Quick start

```python
from math import pi
from dnb import Pipeline, FileSource, PipelineConfig, EventType
from dnb.modules import WaveletConvolution, TargetWaveDetector, AmplitudeMonitor, StimTrigger

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

### From config file

```python
from dnb.config import build_pipeline
pipeline = build_pipeline("config.yaml")
events = pipeline.run_offline()
```

## Installation

```bash
pip install direct-neural-biasing
```

For Blackrock hardware:
```bash
pip install "direct-neural-biasing[live]"
```

From source:
```bash
git clone https://github.com/bushlab-ucl/DirectNeuralBiasing
cd DirectNeuralBiasing
pip install -e ".[dev]"
```

## Offline validation

The notebook `tests/offline-smoke-tests.ipynb` provides interactive validation:

1. **Clean sine** — verify phase detection on a known waveform
2. **Synthetic SWs** — planted slow waves in pink noise, validate against ground truth
3. **IED inhibition** — compare stim counts with/without the AmplitudeMonitor
4. **SNR sweep** — precision/recall/F1 across noise levels
5. **Wavelet inspection** — visualise the time-frequency decomposition
6. **Parameter exploration** — sweep phase tolerance, backoff, etc.

### Synthetic data generation

```python
from dnb.validation.synthetic import generate_synthetic_recording, save_synthetic

signal, gt_events, snr = generate_synthetic_recording(
    n_channels=1, duration_s=120.0, sample_rate=1000.0,
    n_slow_waves=15, n_ieds=5, snr=5.0,
)
path = save_synthetic("test.npz", signal, 1000.0, gt_events)
```

### Ground truth validation

```python
from dnb.validation.ground_truth import validate, Annotation

annotations = [Annotation(timestamp=t, event_type="SW") for t in known_times]
report = validate(detected_events, annotations, time_tolerance=0.5)
print(report.summary())
```

## Modules

### WaveletConvolution

Complex Morlet wavelets with log-spaced frequencies and 1/f-scaled cycle counts. Replaces traditional bandpass filter banks with a single-pass decomposition. Uses overlap-save to eliminate chunk boundary artefacts.

### TargetWaveDetector

Monitors instantaneous phase in a target frequency band. Configurable for any oscillation — set `freq_range=(0.5, 2.0)` for slow waves, `(4, 8)` for theta, etc. Outputs candidate events with phase, amplitude, and frequency metadata.

### AmplitudeMonitor

Watches mean amplitude in a frequency band. Supports absolute threshold mode (`threshold=X`) and ratio mode (`ref_freq_range=(...), ratio_max=0.5`). Use ratio mode for IED rejection: high HF/LF ratio indicates a sharp transient.

### StimTrigger

Combines an activation detector and an optional inhibition detector. Applies per-channel backoff (minimum time between STIM1) and inhibition cooldown (time after IED before allowing stim). Schedules STIM2 (paired pulse) after a configurable delay.

### Downsampler

Decimates from hardware rate (30 kHz) to analysis rate (500 Hz). Maintains its own ring buffer at the downsampled rate. Only needed for live hardware — not needed for synthetic data at 1 kHz.

### AudioStimulator

Plays a WAV file on STIM events. For live closed-loop auditory stimulation during sleep.

## Data sources

| Source | Class | Install |
|---|---|---|
| Saved .npz file | `FileSource` | — |
| NPlay simulator | `NPlaySource` | `[live]` |
| Cerebus NSP hardware | `CerebusSource` | `[live]` |

## File format

DNB uses `.npz` files with keys: `continuous` (n_channels, n_samples), `sample_rate` (scalar), and optionally `channel_ids`, `timestamps`.

## Configuration

All parameters can be set in `config.yaml`. See the included config file for documentation of every parameter.

```bash
python run.py --config config.yaml --offline
```

## License

CC-BY-NC-4.0
