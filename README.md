# DirectNeuralBiasing

Low-latency closed-loop neural signal processing for Blackrock Cerebus devices.

Developed by the [Human Electrophysiology Lab](https://bushlab-ucl.github.io) at UCL.

## Overview

`DirectNeuralBiasing` (DNB) is a library for real-time and offline neural signal processing, designed to interface with Blackrock Microsystems devices for closed-loop neuroscience research. It uses wavelet-based convolution (log-spaced, 1/f-scaled complex Morlet wavelets) to extract instantaneous amplitude and phase across all frequency bands in a single pass — replacing traditional banks of bandpass filters.

## Libraries

- **`src/pythonlib`** — Python library (active). Full pipeline for real-time and offline processing with wavelet decomposition, power estimation, and event detection. Published on [PyPI](https://pypi.org/project/direct-neural-biasing) as `direct-neural-biasing`.
- **`src/rustlib`** — Rust library (on hold). The original implementation; will be updated to match the Python API for cross-language validation. Published on [Crates.io](https://crates.io/crates/direct-neural-biasing).
- **`src/cpplib`** — C++ interface (on hold). Blackrock NSP/NPlay integration layer.

## Quick start (Python)

```bash
pip install direct-neural-biasing
```

For real-time use with Blackrock hardware or NPlay:

```bash
pip install "direct-neural-biasing[live]"
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

### Real-time with NPlay

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

See [`src/pythonlib/README.md`](src/pythonlib/README.md) for full documentation on architecture, wavelet design, event detection, custom modules, and file format.

## Publishing

### Python (PyPI)

Releases are published automatically via GitHub Actions when you push a version tag:

```bash
git tag v2.0.0
git push origin v2.0.0
```

See [`src/pythonlib/README.md`](src/pythonlib/README.md#publishing-to-pypi) for first-time trusted publisher setup.

### Rust (Crates.io) — on hold

```bash
cargo publish
```

### C++ — on hold

```bash
cmake -B build -S . -DCMAKE_INSTALL_PREFIX=../install
cmake --build build --config Release
```

## Links

- [UCL Human Electrophysiology Lab](https://bushlab-ucl.github.io)
- [PyPI](https://pypi.org/project/direct-neural-biasing)
- [Crates.io](https://crates.io/crates/direct-neural-biasing)
- [pycbsdk](https://github.com/CerebusOSS/pycbsdk) — Cerebus communication layer
- [CereLink](https://github.com/CerebusOSS/CereLink) — Blackrock SDK and NPlay tools

## License

CC-BY-NC-4.0