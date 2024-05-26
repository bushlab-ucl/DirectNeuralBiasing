# `DirectNeuralBiasing`

## Overview

`DirectNeuralBiasing` is a Rust package developed by the Human Electrophysiology lab at UCL for closed-loop stimulation of neurons in real-time. The library is designed to interface with Blackrock Microsystems devices for lab use. It is written in Rust with bindings for Python and soon for C++.

## Features

- Real-time signal processing for closed-loop neuroscience experiments.
- Modular structure with filters, detectors, and triggers.
- Python bindings for ease of use.

## Libraries

- `src/rustlib` - Rust code. This is where the business logic lives.
- `src/pythonlib` - Example Python code for importing rust dnb module functions into python projects.
- `src/cpplib` - C++ code for interfacing with Blackrock NSP system and NPlay. Pulls 'extern c' functions from src/Rustlib (wip)

# Using the `PySignalProcessor` from `DirectNeuralBiasing` in Python

## Installation

```sh
pip install direct_neural_biasing # Only works for Windows, Python 3.10 || Python 3.11
```

// how to install from pip
// how to setup PySignalProcessor, add filter, add threshold detector, add slowwave detector, add pulse trigger, run signalprocessor

# Structure and Use of `SignalProcessor` in Rust

### Documentation

This README may be out of date, check out the docs at:
**Crates.io**: https://crates.io/crates/direct-neural-biasing

### Rust Module Overview

The main submodule is `processing`, which includes:

- `signal_processor`: Main component and global logic.
- `filters`: Contains the signal filtering logic.
- `detectors`: Handles detection algorithms.
- `triggers`: Manages event triggering based on detections.

## Signal Processor

The `SignalProcessor` is the backbone of `DirectNeuralBiasing`. You can add filters, detectors, and triggers to it. It processes an array of samples in a structured manner.

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

1. **Configuration Struct**: `BandPassFilterConfig`

```rust
pub struct BandPassFilterConfig {
    pub id: String,
    pub f0: f64,
    pub fs: f64,
    pub downsample_rate: usize,
}
```

2. **BandPassFilter Struct**: `BandPassFilter`

```rust
pub struct BandPassFilter {
    config: BandPassFilterConfig,
    a: [f64; 3],
    b: [f64; 3],
    x: [f64; 2],
    y: [f64; 2],
}

impl FilterInstance for BandPassFilter {
    fn id(&self) -> &str { ... }
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, filter_id: &str) { ... }
}

impl BandPassFilter {
    pub fn new(config: BandPassFilterConfig) -> Self { ... }
    fn calculate_output(&mut self, input: f64) -> f64 { ... }
}
```

## Detectors

Detectors analyze the filtered signals and detect specific events.

### `ThresholdDetector` Struct

1. **Configuration Struct**: `ThresholdDetectorConfig`

```rust
pub struct ThresholdDetectorConfig {
    pub id: String,
    pub filter_id: String,
    pub threshold: f64,
    pub buffer_size: usize,
    pub sensitivity: f64,
}
```

2. **ThresholdDetector Struct**: `ThresholdDetector`

```rust
pub struct ThresholdDetector {
    config: ThresholdDetectorConfig,
    buffer: RingBuffer,
    statistics: Statistics,
}

impl DetectorInstance for ThresholdDetector {
    fn id(&self) -> &str { ... }
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, index: usize, detector_id: &str) { ... }
}

impl ThresholdDetector {
    pub fn new(config: ThresholdDetectorConfig) -> Self { ... }
}
```

### `SlowWaveDetector` Struct

1. **Configuration Struct**: `SlowWaveDetectorConfig`

```rust
pub struct SlowWaveDetectorConfig {
    pub id: String,
    pub filter_id: String,
    pub threshold_sinusoid: f64,
    pub absolute_min_threshold: f64,
    pub absolute_max_threshold: f64,
}
```

2. **SlowWaveDetector Struct**: `SlowWaveDetector`

```rust
pub struct SlowWaveDetector {
    config: SlowWaveDetectorConfig,
    ongoing_wave: Vec<f64>,
    ongoing_wave_idx: Vec<usize>,
    last_sample: f64,
}

impl DetectorInstance for SlowWaveDetector {
    fn id(&self) -> &str { ... }
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, index: usize, detector_id: &str) { ... }
}

impl SlowWaveDetector {
    pub fn new(config: SlowWaveDetectorConfig) -> Self { ... }
    fn analyse_wave(&mut self, results: &mut HashMap<String, f64>, detector_id: &str) -> bool { ... }
    fn find_wave_minima(&self) -> usize { ... }
    fn construct_cosine_wave(&self, peak_idx: usize, wave_length: usize) -> Vec<f64> { ... }
    fn calculate_correlation(&self, sinusoid: &Vec<f64>) -> f64 { ... }
}
```

## Triggers

Triggers are activated based on the detector outputs and manage the event response.

### `PulseTrigger` Struct

1. **Configuration Struct**: `PulseTriggerConfig `

```rust
pub struct PulseTriggerConfig {
    pub id: String,
    pub activation_detector_id: String,
    pub inhibition_detector_id: String,
    pub activation_cooldown: Duration,
    pub inhibition_cooldown: Duration,
}
```

2. **PulseTrigger Struct**: `PulseTrigger`

```rust
pub struct PulseTrigger {
    config: PulseTriggerConfig,
    last_activation_time: Option<Instant>,
    last_inhibition_time: Option<Instant>,
}

impl TriggerInstance for PulseTrigger {
    fn id(&self) -> &str { ... }
    fn evaluate(&mut self, results: &mut HashMap<String, f64>, id: &str) { ... }
}

impl PulseTrigger {
    pub fn new(config: PulseTriggerConfig) -> Self { ... }
}
```
