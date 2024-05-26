# `DirectNeuralBiasing`

## Overview

`DirectNeuralBiasing` is a Rust package developed by the Human Electrophysiology lab at UCL for closed-loop stimulation of neurons in real-time. The library is designed to interface with Blackrock Microsystems devices for lab use. It is written in Rust with bindings for Python and soon for C++.

## Features

- Real-time signal processing for closed-loop neuroscience experiments.
- Modular structure with filters, detectors, and triggers.
- Python bindings for ease of use.

# Using the `PySignalProcessor` from `DirectNeuralBiasing` in Python

## Installation

```sh
pip install direct_neural_biasing
```

Currently only available for Windows: `Python 3.10` || `Python 3.11`

## Running the PySignalProcessor

The following instructions guide you through setting up and running the PySignalProcessor in Python.

An example Jupyter Notebook demonstrating this process can be found in `src/pythonlib/direct-neural-biasing-demo-0.6.5.ipynb`.

### STEP 1 - Setup SignalProcessor

#### 1.1 - Create Signal Processor

First, create a `PySignalProcessor` instance.

```py
import direct_neural_biasing as dnb

verbose = False  # verbose = True gives verbose output in results object for debugging
downsample_rate = 1  # 1 = full sampling rate. Higher numbers create downsampling. Useful for large files and demos

signal_processor = dnb.PySignalProcessor(verbose, downsample_rate)
```

#### 1.2 - Create Filter

Create and add a `BandpassFilter` to the `PySignalProcessor`. Set the filter ID, center frequency (f0), and sample frequency (sample_freq).

```py
filter_id = 'simple_filter'
f0 = 0.5  # bandpass filter center frequency
sample_freq = 1000  # signal sample rate in Hz (example value)

signal_processor.add_filter(filter_id, f0, sample_freq)
```

#### 1.3 - Create Slow Wave Detector

Create and add a `SlowWaveDetector` to the `PySignalProcessor`. Specify the detector ID, filter ID to read from, sinusoid threshold, and absolute amplitude thresholds.

```py
activation_detector_id = 'slow_wave_detector'
sinusoid_threshold = 0.8  # Between 0 and 1
absolute_min_threshold = 0.0
absolute_max_threshold = 100.0

signal_processor.add_slow_wave_detector(
    activation_detector_id,
    filter_id,  # which filtered_signal should the detector read from
    sinusoid_threshold,
    absolute_min_threshold,
    absolute_max_threshold
)
```

#### 1.4 - Create Threshold Detector for IED detection

Create and add a `ThresholdDetector` to the `PySignalProcessor`. Specify the detector ID, filter ID to read from, z-score threshold, buffer size, and sensitivity.

```py
inhibition_detector_id = 'ied_detector'
z_score_threshold = 5.0  # threshold for candidate detection event
buffer_size = 10  # length of buffer - to increase noise resistance
sensitivity = 0.5  # Between 0 and 1. Ratio of values in buffer over threshold required to trigger an 'IED Detected' event.

signal_processor.add_threshold_detector(
    inhibition_detector_id,
    filter_id,  # which filtered_signal should the detector read from
    z_score_threshold,
    buffer_size,
    sensitivity
)
```

#### 1.5 - Create Pulse Trigger

Create and add a `PulseTrigger` to the `PySignalProcessor`. Specify the trigger ID, activation detector ID, inhibition detector ID, and cooldown durations in milliseconds.

```py
trigger_id = 'pulse_trigger'
activation_cooldown_ms = 2000  # duration in milliseconds for cooldown after pulse event
inhibition_cooldown_ms = 2000  # duration in milliseconds for cooldown after IED detection

signal_processor.add_pulse_trigger(
    trigger_id,
    activation_detector_id,  # which detector triggers a pulse - SlowWave in this case
    inhibition_detector_id,  # which detector triggers an inhibition cooldown - IED in this case
    activation_cooldown_ms,
    inhibition_cooldown_ms
)
```

### STEP 2 - Run the Signal Processor

Run the `PySignalProcessor` with your data. The data should be an array of raw signal samples.

```py
data = [...]  # Your raw signal data array
out = signal_processor.run(data)

```

# Structure and Use of `SignalProcessor` in Rust

## Libraries

- `src/rustlib` - Rust code. This is where the business logic lives.
- `src/pythonlib` - Example Python code for importing rust dnb module functions into python projects.
- `src/cpplib` - C++ code for interfacing with Blackrock NSP system and NPlay. Pulls 'extern c' functions from src/Rustlib (wip)

## Documentation

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
