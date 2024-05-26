# Direct Neural Biasing

## Overview

Direct Neural Biasing is a Rust package developed by the Human Electrophysiology lab at UCL for closed-loop stimulation of neurons in real-time. The library is designed to interface with Blackrock Microsystems devices for lab use. It is written in Rust with bindings for Python and soon for C++.

## Features

- Real-time signal processing for closed-loop neuroscience experiments.
- Modular structure with filters, detectors, and triggers.
- Python bindings for ease of use.

## Libraries

- **src/rustlib** - Rust code for functions. This is where the business logic lives.
- **src/pythonlib** - Example Python code for importing rust dnb module functions for python work.
- **src/cpplib** - C++ code for interfacing with Blackrock NSP system and NPlay. Pulls 'extern c' functions from src/Rustlib (wip)

## Structure and Use of `SignalProcessor` in Rust

### Rust Module Overview

The main submodule is `processing`, which includes:

- `filters`: Contains the signal filtering logic.
- `detectors`: Handles detection algorithms.
- `triggers`: Manages event triggering based on detections.

### `SignalProcessor` Class in Rust

#### Example Usage

1. **SignalProcessorConfig Struct**: `SignalProcessorConfig`

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

3. **Adding Components**: `SignalProcessor`
   ```rust
   impl SignalProcessor {
    pub fn new(config: SignalProcessorConfig) -> Self { ... }
    pub fn add_filter(&mut self, filter: Box<dyn FilterInstance>) { ... }
    pub fn add_detector(&mut self, detector: Box<dyn DetectorInstance>) { ... }
    pub fn add_trigger(&mut self, trigger: Box<dyn TriggerInstance>) { ... }
    pub fn run(&mut self, raw_samples: Vec<f64>) -> Vec<HashMap<String, f64>> { ... }
   }
   ```
