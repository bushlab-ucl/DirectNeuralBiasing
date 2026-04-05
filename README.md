# direct-neural-biasing

Low-latency closed-loop neural signal processing for Blackrock Cerebus devices.

Developed by the [Human Electrophysiology Lab](https://bushlab-ucl.github.io) at UCL.

## Overview

`direct-neural-biasing` (DNB) is a Python library for real-time and offline neural signal processing. It uses wavelet-based convolution (log-spaced, 1/f-scaled complex Morlet wavelets) to extract instantaneous amplitude and phase across all frequency bands in a single pass — replacing traditional banks of bandpass filters.

The library provides a unified pipeline that works identically in both modes:

- **`run_online()`** — real-time closed-loop processing from Blackrock NSP hardware or NPlay simulator
- **`run_offline()`** — batch processing from saved files, producing the same outputs

The Python API is designed to mirror the Rust implementation one-to-one, enabling cross-language validation.

## Quick start

```python
from dnb import Pipeline, NPlaySource
from dnb.modules import WaveletConvolution, EventDetector, PowerEstimator

pipeline = Pipeline(
    source=NPlaySource(),
    modules=[
        WaveletConvolution(freq_min=1, freq_max=200, n_freqs=40),
        PowerEstimator(),
        EventDetector(freq_range=(80, 250), threshold_std=3.0),
    ],
)
pipeline.on_event("ripple", lambda e: print(f"Ripple at {e.timestamp:.3f}s"))
pipeline.run_online()
```

### Offline from saved data

```python
from dnb import Pipeline, FileSource, PipelineConfig
from dnb.modules import WaveletConvolution, EventDetector

pipeline = Pipeline(
    source=FileSource("neural_data.npz"),
    modules=[
        WaveletConvolution(freq_min=1, freq_max=200, n_freqs=40),
        EventDetector(freq_range=(80, 250), threshold_std=3.0),
    ],
    config=PipelineConfig(sample_rate=30000, n_channels=83),
)
events = pipeline.run_offline(output_path="results.npz")
print(f"Detected {len(events)} events")
```

Note: when using `FileSource`, the pipeline automatically adopts the file's actual sample rate, channel count, and channel IDs. The values in `PipelineConfig` serve as defaults and are overridden by what the file contains.

## Installation

```bash
pip install direct-neural-biasing
```

For real-time use with Blackrock hardware or NPlay, install the live extras:

```bash
pip install "direct-neural-biasing[live]"
```

Or from source:

```bash
git clone https://github.com/bushlab-ucl/DirectNeuralBiasing
cd DirectNeuralBiasing
pip install -e ".[dev]"
# For live sources:
pip install -e ".[dev,live]"
```

### Dependencies

Core (always installed):

- `numpy >= 1.24`
- `scipy >= 1.10`
- `pyyaml >= 6.0`

Optional — live sources (`pip install "direct-neural-biasing[live]"`):

- `pycbsdk >= 0.3`

Optional — validation figures (`pip install "direct-neural-biasing[validation]"`):

- `matplotlib >= 3.5`

## Scripts

DNB ships with two scripts at the repository root. Neither is part of the installed package — they are entry points you run directly.

### `run.py` — config-driven pipeline runner

The main entry point for running pipelines without writing Python code. All parameters are read from `config.yaml`.

```bash
# Online (live from hardware/NPlay)
python run.py --config config.yaml

# Offline (batch processing from file)
python run.py --config config.yaml --offline

# Offline + validate detections against ground truth annotations
python run.py --config config.yaml --offline --validate annotations.csv

# Synthetic validation: sweep SNR levels and produce debug figures
python run.py --config config.yaml --snr-sweep
```

The `--snr-sweep` mode generates synthetic recordings with planted slow waves at varying signal-to-noise ratios, runs detection on each, and reports precision, recall, and F1 at every level. If `matplotlib` is installed it also saves figures (precision/recall/F1 vs SNR, timing error boxplots, detection count breakdowns).

### `smoke_test.py` — quick sanity check

A developer smoke test that confirms the pipeline detects events on synthetic data and optionally tests live hardware connectivity.

```bash
# Offline only (no hardware needed)
python smoke_test.py

# Also test live NPlay connection
python smoke_test.py --live nplay

# Single channel, longer run
python smoke_test.py --live nplay --channel 5 --seconds 30
```

## Architecture

```
Source --> RingBuffer --> [Module chain] --> EventBus --> Outputs
```

The pipeline writes every incoming chunk into a thread-safe ring buffer before passing it through the module chain. Modules receive a reference to the ring buffer via `ProcessResult.ring_buffer`, allowing them to read historical samples when needed (e.g. for overlap-save convolution).

### Data sources

| Source          | Class           | Description                     | Install extra |
| --------------- | --------------- | ------------------------------- | ------------- |
| NSP hardware    | `CerebusSource` | Live from Blackrock Cerebus NSP | `[live]`      |
| NPlay simulator | `NPlaySource`   | From NPlay replay instance      | `[live]`      |
| Saved file      | `FileSource`    | From `.npz` files               | —             |

All sources implement the `DataSource` ABC and produce `DataChunk` objects with shape `(n_channels, n_samples)`.

`FileSource` exposes a `resolved_config` property after `connect()` which reflects the file's actual parameters (sample rate, channel count, channel IDs). The pipeline automatically adopts this config so that the ring buffer and all modules are configured correctly regardless of what was passed in the initial `PipelineConfig`.

### Processing modules

Modules are composable and chainable. Each receives a `ProcessResult` from the previous module.

| Module               | Description                                                                                                       |
| -------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `Downsampler`        | Decimates from hardware rate (e.g. 30 kHz) to analysis rate (e.g. 500 Hz). Maintains its own ring buffer at the downsampled rate so downstream modules get consistent history. |
| `WaveletConvolution` | Complex Morlet wavelets, log-spaced, 1/f-scaled. Produces amplitude + phase at every (channel, freq, time) point. |
| `PowerEstimator`     | Band-specific power from wavelet output (delta, theta, alpha, beta, gamma).                                       |
| `SlowWaveDetector`   | Phase-targeting slow wave detector. Fires STIM1 at a configurable phase of the slow oscillation, with amplitude gating, HF rejection, backoff, and paired STIM2 scheduling. Extracts ±1s raw signal windows around each detection. |
| `EventDetector`      | Threshold-based event detection on wavelet amplitude envelopes.                                                   |
| `AudioStimulator`    | Plays a WAV file on STIM events (requires `simpleaudio`).                                                         |

**Module ordering**: The pipeline validates module order at startup. `Downsampler` must come before `WaveletConvolution`. Modules that consume wavelet data (`EventDetector`, `PowerEstimator`, `SlowWaveDetector`) must be placed after `WaveletConvolution`.

### Custom modules

Subclass `Module` to add your own processing:

```python
from dnb.modules import Module, ProcessResult
from dnb.core import PipelineConfig

class MyModule(Module):
    def configure(self, config: PipelineConfig) -> None:
        self.sample_rate = config.sample_rate

    def process(self, result: ProcessResult) -> ProcessResult:
        if result.wavelet is not None:
            phase = result.wavelet.phase  # (n_ch, n_freqs, n_samples)
            # ... your processing here ...

        # Access historical data from the ring buffer if needed:
        if result.ring_buffer is not None:
            history = result.ring_buffer.read(1000)  # last 1000 samples
        return result
```

## Configuration

All pipeline and detection parameters can be set in a YAML config file:

```yaml
pipeline:
  sample_rate: 30000
  n_channels: 83
  channel: 5
  chunk_duration: 0.5
  source: nplay            # nplay | cerebus | file
  file_path: recording.npz # only for source: file

wavelet:
  freq_min: 0.5
  freq_max: 30.0
  n_freqs: 10

slow_wave:
  target_phase: 0.0
  phase_tolerance: 0.15
  freq_range: [0.5, 2.0]
  amp_min: 50.0
  amp_max: 10000.0
  backoff_s: 5.0
  warmup_chunks: 10
  event_window_s: 1.0    # ±1s raw signal saved around each detection

downsampler:
  target_rate: 500.0

audio:
  enabled: true
  wav_path: assets/pink_noise_short.wav
  trigger_on: [STIM1]

validation:
  time_tolerance_s: 0.05
  snr_levels: [1.0, 2.0, 3.0, 5.0, 10.0]
```

Pass the config file to `run.py`:

```bash
python run.py --config config.yaml --offline
```

## Wavelet design

The library uses complex Morlet wavelets with:

- **Log-spaced centre frequencies** from `freq_min` to `freq_max`, matching the 1/f spectral structure of neural signals
- **1/f-scaled cycle counts**: `n_cycles(f) = n_cycles_base * (f / f_min)`, giving constant fractional bandwidth — low frequencies get long wavelets (good frequency resolution), high frequencies get short wavelets (good time resolution)
- **FFT-based convolution** for efficiency on typical chunk sizes
- **Overlap-save**: when a ring buffer is available, the module reads historical samples as a prefix before convolving. This eliminates edge artefacts at chunk boundaries — the transient falls in the discarded prefix rather than corrupting the output. The overlap length equals the longest wavelet kernel minus one sample.

The output is the full analytic signal at every `(channel, frequency, time)` point, from which you can read `.amplitude`, `.phase`, and `.power` directly.

## Event detection

The `SlowWaveDetector` monitors wavelet phase in a slow oscillation band and fires stimulation events when the signal reaches a target phase of the slow wave cycle.

Key parameters:

- `target_phase` — phase angle to trigger at (radians; 0 = positive peak, π = negative peak)
- `phase_tolerance` — half-width of the phase window (radians)
- `freq_range` — `(low_hz, high_hz)` band to monitor for slow oscillations
- `amp_min` / `amp_max` — amplitude gates to reject noise and artefacts
- `hf_freq_range` / `hf_ratio_max` — high-frequency rejection to avoid triggering on IEDs
- `backoff_s` — minimum seconds between stimulations
- `stim2_delay_s` / `stim2_window_s` — paired STIM2 scheduling
- `warmup_chunks` — initial chunks used only for baseline estimation
- `event_window_s` — ±seconds of raw signal to save around each detection

The `EventDetector` provides simpler threshold-based detection on amplitude envelopes, using `scipy.ndimage.label` for robust region identification.

## Validation

DNB includes three validation tools in `dnb.validation`:

### Synthetic validation

Generates recordings with 1/f (pink) noise backgrounds and planted slow waves and IEDs at configurable signal-to-noise ratios. Runs the detection pipeline on each, matches detections to ground truth, and reports precision, recall, and F1.

```bash
python run.py --config config.yaml --snr-sweep
```

Produces CSV results and (with matplotlib) debug figures: precision/recall/F1 vs SNR, timing error boxplots, and detection count breakdowns.

### Ground truth validation

Validates detections against expert-annotated recordings. Loads annotation CSVs with SW and IED timestamps, matches detections via nearest-neighbour within a configurable time tolerance, and computes precision, recall, F1, sensitivity, and specificity.

```bash
python run.py --config config.yaml --offline --validate annotations.csv
```

### Rust vs Python comparison

Cross-language validation: runs both implementations on identical input and compares outputs numerically. (Planned.)

## File format

DNB uses `.npz` files with these keys:

| Key           | Shape                     | Description                           |
| ------------- | ------------------------- | ------------------------------------- |
| `continuous`  | `(n_channels, n_samples)` | Raw or processed neural data          |
| `sample_rate` | scalar                    | Sampling rate in Hz                   |
| `channel_ids` | `(n_channels,)`           | Optional channel identifiers          |
| `timestamps`  | `(n_samples,)`            | Optional sample timestamps in seconds |

## Publishing to PyPI

Releases are published automatically via GitHub Actions when you push a version tag.

```bash
git tag v2.1.0
git push origin v2.1.0
```

This triggers `.github/workflows/publish.yml` which runs the test suite, builds the package, and uploads to PyPI using [trusted publishing](https://docs.pypi.org/trusted-publishers/).

### First-time setup (once per project)

On PyPI, go to your project → Settings → Publishing → add a new trusted publisher with repository `bushlab-ucl/DirectNeuralBiasing`, workflow `publish.yml`, and environment `pypi`.

On GitHub, go to Settings → Environments → create an environment called `pypi`.

That's it — no API tokens to manage.

## Links

- [UCL Human Electrophysiology Lab](https://bushlab-ucl.github.io)
- [pycbsdk](https://github.com/CerebusOSS/pycbsdk) — Cerebus communication layer
- [CereLink](https://github.com/CerebusOSS/CereLink) — Blackrock SDK and NPlay tools

## License

CC-BY-NC-4.0
