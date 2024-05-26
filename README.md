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

#### Some Other Loose Bits:

- **Rust DNB Server (rustlib)** - Generates a sample LFP signal and occasional Interictal spikes and SWRs. Streams to :8080.
- **Rust DNB Client (rustlib)** - Listens to port 8080 and outputs signal to terminal.
- **BlackrockNSP (cpplib)** - Visual studio project for connecting to realtime NSP/NPlay stream to run DNB closed-loop code.

## Structure and Use of `SignalProcessor` in Rust

### Rust Module Overview

The main submodule is `processing`, which includes:

- `filters`: Contains the signal filtering logic.
- `detectors`: Handles detection algorithms.
- `triggers`: Manages event triggering based on detections.

### `SignalProcessor` Class in Rust

#### Example Usage

1. **Configuration Struct**: `SignalProcessorConfig`
   ```rust
   pub struct SignalProcessorConfig {
       pub verbose: bool,
       pub log_to_file: bool,
       pub downsample_rate: usize,
   }
   ```
