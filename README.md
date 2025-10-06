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

## RUST BUILD

cargo build --release --no-default-features --features cpp

## CPP BUILD

cmake -B build -S . -DCMAKE_INSTALL_PREFIX=../install

cmake --build build --config Release

## PYTHON BUILD

maturin build --interpreter python3.11 && maturin build --interpreter python3.10

maturin publish --interpreter python3.11 && maturin publish --interpreter python3.10

### summary/description build bug

- Currently exporting to PyPi and Cargo require slightly different config.
- PyPi needs `summary` in [package.metadata.maturin]
- Cargo needs `description` in [package]
- There's probably a way to make it work in both cases, but I haven't found it yet.
- For now you need to comment and uncomment them to post.
