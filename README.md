# `DirectNeuralBiasing`

## Overview

`DirectNeuralBiasing` is a Rust package developed by the Human Electrophysiology Lab at UCL for low-latency, closed-loop neuroscience research. The library is designed to interface with Blackrock Microsystems devices for lab use. It is written in `Rust` with bindings for `Python` and soon `C++`.

## Features

- Real-time signal processing for closed-loop neuroscience experiments.
- Modular structure with filters, detectors, and triggers.
- Python bindings for ease of use.

## Libraries

- `src/rustlib` - Rust code. This is where the business logic lives.
- `src/pythonlib` - Example Python code for importing rust dnb module functions into python projects.
- `src/cpplib` - C++ code for interfacing with Blackrock NSP system and NPlay.

## Links

- `UCL Human Electrophysiology Lab`: https://bushlab-ucl.github.io
- `Crates.io`: https://crates.io/crates/direct-neural-biasing
- `PyPi`: https://pypi.org/project/direct-neural-biasing

# Using the `PySignalProcessor` from `DirectNeuralBiasing` in Python

## Installation

Install and/or upgrade `DirectNeuralBiasing` using pip (sometimes you need to run it twice to upgrade):

```sh
$ pip install direct_neural_biasing --upgrade
```

Currently only available for Windows: `Python 3.10` || `Python 3.11`

(also, install other modules if you don't have them)

```sh
$ pip install direct_neural_biasing scipy matplotlib numpy pandas mne
```

## Running the PySignalProcessor

The following instructions guide you through setting up and running the PySignalProcessor in Python.

An example Jupyter Notebook demonstrating this process can be found in: \
[`src/pythonlib/direct-neural-biasing-demo-0.7.x.ipynb`](https://github.com/bushlab-ucl/DirectNeuralBiasing/blob/main/src/pythonlib/direct-neural-biasing-demo-0.7.x.ipynb)

### STEP 1 - Import `direct_neural_biasing`

```py
import direct_neural_biasing as dnb
```

### STEP 2 - Setup SignalProcessor

#### 2.1 - Create Signal Processor

First, create a `PySignalProcessor` instance.

```py
verbose = False  # verbose = True gives verbose output in results object for debugging
signal_processor = dnb.PySignalProcessor(verbose, sample_freq)
```

#### 2.2 - Create Filter

Create and add a `BandpassFilter` to the `PySignalProcessor`. Set the filter ID, center frequency (f0), and sample frequency (sample_freq).

```py
filter_id = 'bandpass_filter_slow_wave'
f_low = 0.5 # cutoff_low
f_high = 4.0 # cutoff_high

signal_processor.add_filter(slow_wave_filter_id, f_low, f_high, sample_freq)
```

#### 2.3 - Create Slow Wave Detector

Create and add a `SlowWaveDetector` to the `PySignalProcessor`. Specify the detector ID, filter ID to read from, sinusoid threshold, and absolute amplitude thresholds.

```py
slow_wave_detector_id = 'slow_wave_detector'
z_score_threshold = 1.0 # candidate wave amplitude threhsold
sinusoidness_threshold = 0.5 # cosine wave correlation, between 0 and 1.

signal_processor.add_slow_wave_detector(
    slow_wave_detector_id,
    slow_wave_filter_id, # which filtered_signal should the detector read from
    z_score_threshold,
    sinusoidness_threshold,
)
```

#### 2.4 - Create Threshold Detector for IED detection

Create and add a `ThresholdDetector` to the `PySignalProcessor`. Specify the detector ID, filter ID to read from, z-score threshold, buffer size, and sensitivity.

```py
inhibition_detector_id = 'ied_detector' # unique id
z_score_threshold = 2.0  # threshold for candidate detection event
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

#### 2.5 - Create Pulse Trigger

Create and add a `PulseTrigger` to the `PySignalProcessor`. Specify the trigger ID, activation detector ID, inhibition detector ID, and cooldown durations in milliseconds.

```py
trigger_id = 'pulse_trigger' # unique id
activation_cooldown_ms = 2000  # duration in milliseconds for cooldown after pulse event
inhibition_cooldown_ms = 2000  # duration in milliseconds for cooldown after inhibition event

signal_processor.add_pulse_trigger(
    trigger_id,
    activation_detector_id,  # which detector triggers a pulse - SlowWave in this case
    inhibition_detector_id,  # which detector triggers an inhibition cooldown - IED in this case
    activation_cooldown_ms,
    inhibition_cooldown_ms
)
```

### STEP 3 - Run the Signal Processor

Run the `PySignalProcessor` with your data. The data should be an array of raw signal samples.

```py
data = [...]  # Your raw signal data array
out = signal_processor.run_chunk(data) # run data in chunks
```

Example file for iterating through data and reading events with context to a list.

```py
from collections import deque
import time

def data_generator(data, chunk_size):
    for i in range(0, len(data), chunk_size):
        print(f'processing chunk {i // chunk_size + 1} of size: {chunk_size}')
        yield data[i:i + chunk_size]

def process_chunk(signal_processor, data_chunk):
    return signal_processor.run_chunk(data_chunk)

def run_in_series(processor, data_generator, chunk_size, context_size):
    buffer_size = (context_size * 2) + 1
    event_buffer = deque(maxlen=buffer_size)  # Ring buffer with context samples
    results = []  # List to hold the final output arrays
    
    # Reset index to zero each time you re-analyse the data
    processor.reset_index()
    
    chunk_count = 0
    detected_events = 0
    
    for chunk in data_generator:
        if len(chunk) > 0:
            chunk_count += 1
            start_time = time.time()  # Start timer before analysis
            chunk_output = process_chunk(processor, chunk)
            duration = time.time() - start_time

            print(f"Processed chunk {chunk_count} in {duration:.4f}s")

            for sample_result in chunk_output:
                event_buffer.append(sample_result)

                # If the buffer is full, analyze the middle sample and remove the oldest sample
                if len(event_buffer) >= buffer_size:
                    # Check if the sample in the middle of the buffer is an event
                    middle_sample = event_buffer[context_size]
                    
                    # If the middle sample is an event, store the context
                    if middle_sample.get("triggers:pulse_trigger:triggered", 0.0) == 1.0:
                        detected_events += 1
                        print(f"Detected event {detected_events} at buffer index {context_size}")

                        # Append the entire buffer to results
                        results.append(list(event_buffer))

                    # Pop the oldest sample
                    event_buffer.popleft()

    return results

# Example usage
chunk_size = int(1e5)  # Chunk size for processing
context_size = 2000  # Number of samples to include as context around events
data_gen = data_generator(data, chunk_size)
results = run_in_series(signal_processor, data_gen, chunk_size, context_size)

# The results object now contains the final output - a list of lists
# Each list contains <context_size> samples either side of an event
# i.e. if context_size is 2e4 (2000), each list will be 4001 samples long, and the event will be at sample index 2000
```

# Structure and Use of `SignalProcessor` in Rust

### Documentation

This README may be out of date, check out the docs at:
**Crates.io**: https://crates.io/crates/direct-neural-biasing

### Rust Module Overview

The main submodule is `processing`, which includes:

- `signal_processor`: Contains the main component and global logic.
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
    pub filters: HashMap<String, Box<dyn FilterInstance>>,
    pub detectors: HashMap<String, Box<dyn DetectorInstance>>,
    pub triggers: HashMap<String, Box<dyn TriggerInstance>>,
    pub config: SignalProcessorConfig,
    pub results: HashMap<String, f64>,
    pub keys: Keys,
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
    pub f_low: f64,
    pub f_high: f64,
    pub fs: f64,
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
    pub z_score_threshold: f64,
    pub sinusoidness_threshold: f64,
}
```

2. **SlowWaveDetector Struct**: `SlowWaveDetector`

```rust
pub struct SlowWaveDetector {
    config: SlowWaveDetectorConfig,
    statistics: Statistics,
    last_sample: f64,
    is_downwave: bool,
    ongoing_wave_z_scores: Vec<f64>,
    downwave_start_index: Option<usize>,
    downwave_end_index: Option<usize>,
    predicted_next_maxima_index: Option<usize>,
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

# Known Bugs

### summary/description build bug

- Currently exporting to PyPi and Cargo require slightly different config.
- PyPi needs `summary` in [package.metadata.maturin]
- Cargo needs `description` in [package]
- There's probably a way to make it work in both cases, but I haven't found it yet.
- For now you need to comment and uncomment them to post.
