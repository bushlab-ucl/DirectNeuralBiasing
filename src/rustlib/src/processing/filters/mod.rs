/// The `filters` module contains various signal processing filters used in the Direct Neural Biasing system.
///
/// This module includes the `FilterInstance` trait which defines the basic functionality
/// that any filter should implement. Filters are used to process raw neural signals
/// to isolate specific frequency components or remove noise.
pub mod bandpass;

use std::collections::HashMap;

/// Trait defining the basic operations for a filter instance.
///
/// Filters implementing this trait can process neural signal samples and return filtered results.
pub trait FilterInstance: Send {
    /// Returns the unique identifier for the filter instance.
    fn id(&self) -> &str;

    /// Processes a single sample and updates the provided results map with the filtered output.
    ///
    /// # Arguments
    ///
    /// * `results` - A mutable reference to a `HashMap` storing the signal processing results.
    /// * `filter_id` - The identifier for the filter being used, used as a key in the results map.
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, filter_id: &str);
}
