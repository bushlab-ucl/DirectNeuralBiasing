//! Direct Neural Biasing is a rust package for the real time, closed-loop stimulation of neurons.
//!
//! It is being developed by the Human Electrophysiology lab at UCL.
//!
//! It is currently in development.
//!
//! It's primarily written in Rust, but has bindings for Python and (soon) C++, to interface with Blackrock Microsystems devices for lab use.

/// - Local is a test module for Rust users, to debug the processing module.
#[cfg(not(feature = "python-extension"))]
pub mod local;

/// - Processing is the main module, it has code for the signal processor, which itself is split up into filters, detectors, and triggers (for now).
pub mod processing;

/// - Tests contains some tests for the Blackrock C++ bindings.
pub mod tests;

/// - Utility functions, such as reading and writing files.
pub mod utils;

/// - For running the local debug.
#[cfg(not(feature = "python-extension"))]
pub fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 {
        match args[1].as_str() {
            "client" => local::client::run().unwrap(),
            "server" => local::server::run().unwrap(),
            _ => println!("Invalid argument, please use 'client' or 'server'"),
        }
    } else {
        println!("Please specify 'client' or 'server' as argument");
    }
}
