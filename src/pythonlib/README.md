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

Optional — live sources (`pip install "direct-neural-biasing[live]"`):

- `pycbsdk >= 0.3`

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
| `WaveletConvolution` | Complex Morlet wavelets, log-spaced, 1/f-scaled. Produces amplitude + phase at every (channel, freq, time) point. |
| `PowerEstimator`     | Band-specific power from wavelet output (delta, theta, alpha, beta, gamma).                                       |
| `EventDetector`      | Threshold-based event detection on wavelet amplitude envelopes.                                                   |

**Module ordering**: The pipeline validates module order at startup. Modules that consume wavelet data (`EventDetector`, `PowerEstimator`) should be placed after `WaveletConvolution` in the chain. If they appear before it, a warning is logged and those modules will silently skip processing.

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

## Wavelet design

The library uses complex Morlet wavelets with:

- **Log-spaced centre frequencies** from `freq_min` to `freq_max`, matching the 1/f spectral structure of neural signals
- **1/f-scaled cycle counts**: `n_cycles(f) = n_cycles_base * (f / f_min)`, giving constant fractional bandwidth — low frequencies get long wavelets (good frequency resolution), high frequencies get short wavelets (good time resolution)
- **FFT-based convolution** for efficiency on typical chunk sizes
- **Overlap-save**: when a ring buffer is available, the module reads historical samples as a prefix before convolving. This eliminates edge artefacts at chunk boundaries — the transient falls in the discarded prefix rather than corrupting the output. The overlap length equals the longest wavelet kernel minus one sample.

The output is the full analytic signal at every `(channel, frequency, time)` point, from which you can read `.amplitude`, `.phase`, and `.power` directly.

## Event detection

The `EventDetector` monitors wavelet amplitude envelopes in a specified frequency band and emits events when amplitude exceeds a threshold (in standard deviations above a running mean).

Key parameters:

- `freq_range` — `(low_hz, high_hz)` band to monitor
- `threshold_std` — number of standard deviations for detection (default 3.0)
- `min_duration` — minimum event duration in seconds (default 0.02)
- `cooldown` — minimum seconds between events on the same channel (default 0.1)
- `warmup_chunks` — number of initial chunks used only for baseline estimation, during which no events are emitted (default 5). This prevents false detections from unstable running statistics at the start of a recording.

Contiguous above-threshold regions are identified using `scipy.ndimage.label` for robust handling of edge cases.

## File format

DNB uses `.npz` files with these keys:

| Key           | Shape                     | Description                           |
| ------------- | ------------------------- | ------------------------------------- |
| `continuous`  | `(n_channels, n_samples)` | Raw or processed neural data          |
| `sample_rate` | scalar                    | Sampling rate in Hz                   |
| `channel_ids` | `(n_channels,)`           | Optional channel identifiers          |
| `timestamps`  | `(n_samples,)`            | Optional sample timestamps in seconds |

## Validation (planned)

Three validation pipelines are stubbed in `dnb.validation`:

1. **Synthetic data** — generate recordings with planted events, measure detection accuracy
2. **Rust vs Python** — run both implementations on identical input, compare outputs numerically
3. **Ground truth** — validate against expert-annotated real recordings (precision, recall, F1)

## Publishing to PyPI

Releases are published automatically via GitHub Actions when you push a version tag.

```bash
git tag v2.0.0
git push origin v2.0.0
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
