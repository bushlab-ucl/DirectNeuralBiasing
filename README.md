# Direct Neural Biasing

## Overview

Direct Neural Biasing is a Rust package developed by the Human Electrophysiology lab at UCL for closed-loop stimulation of neurons in real-time. The library is designed to interface with Blackrock Microsystems devices for lab use. It is written in Rust with bindings for Python and soon for C++.

## Features

- Real-time signal processing for closed-loop neuroscience experiments.
- Modular structure with filters, detectors, and triggers.
- Python bindings for ease of use.

## Libraries

- **src/rustlib** - Rust code for functions. This is where the business logic lives.
- **src/pythonlib** - Example Python code for importing rust dnb module functions into python projects.
- **src/cpplib** - C++ code for interfacing with Blackrock NSP system and NPlay. Pulls 'extern c' functions from src/Rustlib (wip)

# Structure and Use of `SignalProcessor` in Rust

### Rust Module Overview

The main submodule is `processing`, which includes:

- `signal_processor.rs`: Main module.
- `./filters`: Contains the signal filtering logic.
- `./detectors`: Handles detection algorithms.
- `./triggers`: Manages event triggering based on detections.

## Signal Processor

The Signal Processor is the backbone of the program. You can add filters, detectors, and triggers to it. It processes an array of samples in a structured manner.

### `SignalProcessor` Struct

1. **Configuration Struct**: `SignalProcessorConfig`

```rust
pub struct SignalProcessorConfig {
    pub verbose: bool,
    pub downsample_rate: usize,
}
```

2. **SignalProcessor Struct**: `SignalProcessor`

```rust
pub struct SignalProcessor {
    pub index: usize,
    pub sample_count: usize,
    pub filters: HashMap<String, Box<dyn FilterInstance>>,
    pub detectors: HashMap<String, Box<dyn DetectorInstance>>,
    pub triggers: HashMap<String, Box<dyn TriggerInstance>>,
    pub config: SignalProcessorConfig,
    pub results: HashMap<String, f64>,
}
```

3. **SignalProcessor Methods**: `SignalProcessor`

```rust
impl SignalProcessor {
    pub fn new(config: SignalProcessorConfig) -> Self { ... }
    pub fn add_filter(&mut self, filter: Box<dyn FilterInstance>) { ... }
    pub fn add_detector(&mut self, detector: Box<dyn DetectorInstance>) { ... }
    pub fn add_trigger(&mut self, trigger: Box<dyn TriggerInstance>) { ... }
    pub fn run(&mut self, raw_samples: Vec<f64>) -> Vec<HashMap<String, f64>> { ... }
}
```

## Filters

Filters are used to preprocess the raw signals. An example filter is the `BandPassFilter`.

### `BandPassFilter` Struct

1. **Configuration Struct**: `BandPassFilterConfig `

```rust
pub struct BandPassFilterConfig {
    pub id: String,
    pub f0: f64,
    pub fs: f64,
    pub downsample_rate: usize,
}
```

2. **BandPassFilter Struct**: `BandPassFilter `

```rust
pub struct BandPassFilter {
    config: BandPassFilterConfig,
    a: [f64; 3],
    b: [f64; 3],
    x: [f64; 2],
    y: [f64; 2],
}
```

3. **BandPassFilter Methods**: `BandPassFilter `

```rust
impl FilterInstance for BandPassFilter {
    fn id(&self) -> &str { ... }
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, filter_id: &str) { ... }
}
```

```rust
impl BandPassFilter {
    pub fn new(config: BandPassFilterConfig) -> Self { ... }
    fn calculate_output(&mut self, input: f64) -> f64 { ... }
}
```

## Detectors

Detectors analyze the filtered signals and detect specific events.

### `ThresholdDetector` Struct

1. **Configuration Struct**: `ThresholdDetectorConfig  `

```rust
pub struct ThresholdDetectorConfig {
    pub id: String,
    pub filter_id: String,
    pub threshold: f64,
    pub buffer_size: usize,
    pub sensitivity: f64,
}
```

2. **ThresholdDetector Struct**: `ThresholdDetector  `

```rust
pub struct ThresholdDetector {
    config: ThresholdDetectorConfig,
    buffer: RingBuffer,
    statistics: Statistics,
}
```

3. **ThresholdDetector Methods**: `ThresholdDetector `

```rust
impl DetectorInstance for ThresholdDetector {
    fn id(&self) -> &str { ... }
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, index: usize, detector_id: &str) { ... }
}
```

```rust
impl ThresholdDetector {
    pub fn new(config: ThresholdDetectorConfig) -> Self { ... }
}
```
