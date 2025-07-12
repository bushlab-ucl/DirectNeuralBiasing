//! Direct Neural Biasing is a rust package for the real time, closed-loop stimulation of neurons.
//!
//! It is being developed by the Human Electrophysiology lab at UCL.
//!
//! It is currently in development.
//!
//! It's primarily written in Rust, but has bindings for Python and (soon) C++, to interface with Blackrock Microsystems devices for lab use.

/// - Local is a test module for Rust users, to debug the processing module.
// #[cfg(not(feature = "python-extension"))]
pub mod local;

/// - Main rust source code. Contains code for the signal processor, which itself is split up into filters, detectors, and triggers (for now).
pub mod processing;

/// - Tests contains some tests for the Blackrock C++ bindings.
// #[cfg(not(feature = "python-extension"))]
pub mod tests;

/// - Utility functions, such as reading and writing files.
pub mod utils;

/// - Bindings for Python and C++ (wip).
pub mod bindings;

/// - Configuration system for YAML-based settings
pub mod config;

// Add this to your lib.rs file
#[cfg(feature = "cpp")]
pub use bindings::cpp::*;

#[cfg(feature = "python")]
use pyo3::prelude::*;
