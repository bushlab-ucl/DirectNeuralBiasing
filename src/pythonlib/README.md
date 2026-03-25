# direct-neural-biasing

Low-latency closed-loop neural signal processing for Blackrock Cerebus devices.

Developed by the [Human Electrophysiology Lab](https://bushlab-ucl.github.io) at UCL.

## Overview

`direct-neural-biasing` (DNB) is a Python library for real-time and offline neural signal processing. It uses wavelet-based convolution (log-spaced, 1/f-scaled complex Morlet wavelets) to extract instantaneous amplitude and phase across all frequency bands in a single pass — replacing traditional banks of bandpass filters.

The library provides a unified pipeline that works identically in both modes:

- **`run_live()`** — real-time closed-loop processing from Blackrock NSP hardware or NPlay simulator
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
pipeline.run_live()
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

## Installation

```bash
pip install direct-neural-biasing
```

Or from source:

```bash
git clone https://github.com/bushlab-ucl/DirectNeuralBiasing
cd DirectNeuralBiasing
pip install -e ".[dev]"
```

### Dependencies

- `numpy >= 1.24`
- `scipy >= 1.10`
- `pycbsdk >= 0.3` (for live sources only)

## Architecture

```
Source --> RingBuffer --> [Module chain] --> EventBus --> Outputs
```

### Data sources

| Source | Class | Description |
|--------|-------|-------------|
| NSP hardware | `CerebusSource` | Live from Blackrock Cerebus NSP |
| NPlay simulator | `NPlaySource` | From NPlay replay instance |
| Saved file | `FileSource` | From `.npz` files |

All sources implement the `DataSource` ABC and produce `DataChunk` objects with shape `(n_channels, n_samples)`.

### Processing modules

Modules are composable and chainable. Each receives a `ProcessResult` from the previous module.

| Module | Description |
|--------|-------------|
| `WaveletConvolution` | Complex Morlet wavelets, log-spaced, 1/f-scaled. Produces amplitude + phase at every (channel, freq, time) point. |
| `PowerEstimator` | Band-specific power from wavelet output (delta, theta, alpha, beta, gamma). |
| `EventDetector` | Threshold-based event detection on wavelet amplitude envelopes. |

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
        return result
```

## Wavelet design

The library uses complex Morlet wavelets with:

- **Log-spaced centre frequencies** from `freq_min` to `freq_max`, matching the 1/f spectral structure of neural signals
- **1/f-scaled cycle counts**: `n_cycles(f) = n_cycles_base * (f / f_min)`, giving constant fractional bandwidth — low frequencies get long wavelets (good frequency resolution), high frequencies get short wavelets (good time resolution)
- **FFT-based convolution** for efficiency on typical chunk sizes

The output is the full analytic signal at every `(channel, frequency, time)` point, from which you can read `.amplitude`, `.phase`, and `.power` directly.

## File format

DNB uses `.npz` files with these keys:

| Key | Shape | Description |
|-----|-------|-------------|
| `continuous` | `(n_channels, n_samples)` | Raw or processed neural data |
| `sample_rate` | scalar | Sampling rate in Hz |
| `channel_ids` | `(n_channels,)` | Optional channel identifiers |
| `timestamps` | `(n_samples,)` | Optional sample timestamps in seconds |

## Validation (planned)

Three validation pipelines are stubbed in `dnb.validation`:

1. **Synthetic data** — generate recordings with planted events, measure detection accuracy
2. **Rust vs Python** — run both implementations on identical input, compare outputs numerically
3. **Ground truth** — validate against expert-annotated real recordings (precision, recall, F1)

## Links

- [UCL Human Electrophysiology Lab](https://bushlab-ucl.github.io)
- [pycbsdk](https://github.com/CerebusOSS/pycbsdk) — Cerebus communication layer
- [CereLink](https://github.com/CerebusOSS/CereLink) — Blackrock SDK and NPlay tools

## License

CC-BY-NC-4.0
