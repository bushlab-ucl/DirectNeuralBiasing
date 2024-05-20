use super::FilterInstance;
use std::collections::HashMap;

/// Configuration settings for the BandPassFilter.
///
/// This struct holds the necessary parameters for initializing and configuring a bandpass filter.
pub struct BandPassFilterConfig {
    pub id: String,
    pub f0: f64,
    pub fs: f64,
}

/// A bandpass filter implementation for signal processing.
///
/// The `BandPassFilter` processes neural signals by isolating a specific frequency band,
/// allowing frequencies within this band to pass through while attenuating frequencies outside the band.
pub struct BandPassFilter {
    config: BandPassFilterConfig,
    a: [f64; 3],
    b: [f64; 3],
    x: [f64; 2],
    y: [f64; 2],
}

impl FilterInstance for BandPassFilter {
    /// Returns the unique identifier for the filter instance.
    fn id(&self) -> &str {
        &self.config.id
    }

    /// Processes a single sample and updates the provided results map with the filtered output.
    ///
    /// This function retrieves the raw sample from the results map, applies the bandpass filter,
    /// and inserts the filtered sample back into the results map.
    ///
    /// # Arguments
    ///
    /// * `results` - A mutable reference to a `HashMap` storing the signal processing results.
    /// * `filter_id` - The identifier for the filter being used, used as a key in the results map.
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, filter_id: &str) {
        if let Some(&raw_sample) = results.get("global:raw_sample") {
            let filtered_sample = self.calculate_output(raw_sample);
            results.insert(
                format!("filters:{}:filtered_sample", filter_id),
                filtered_sample,
            );
        }
    }
}

impl BandPassFilter {
    /// Creates a new `BandPassFilter` with the given configuration.
    ///
    /// This function initializes the filter coefficients and internal state based on the provided
    /// configuration parameters.
    ///
    /// # Arguments
    ///
    /// * `config` - The configuration settings for the bandpass filter.
    ///
    /// # Returns
    ///
    /// A new `BandPassFilter` instance.
    pub fn new(config: BandPassFilterConfig) -> Self {
        let q = (2.0f64).sqrt() / 2.0; // Example for a Butterworth filter
        let omega = 2.0 * std::f64::consts::PI * config.f0 / config.fs;
        let alpha = f64::sin(omega) / (2.0 * q);

        let b0 = q * alpha;
        let b1 = 0.0;
        let b2 = -q * alpha;
        let a0 = 1.0 + alpha;
        let a1 = -2.0 * f64::cos(omega);
        let a2 = 1.0 - alpha;

        BandPassFilter {
            config,
            a: [a0, a1, a2],
            b: [b0, b1, b2],
            x: [0.0, 0.0],
            y: [0.0, 0.0],
        }
    }

    /// Calculates the filtered output based on the input sample and updates the filter's internal state.
    ///
    /// This function applies the bandpass filter to the input sample, using the filter's coefficients
    /// and internal state to produce the filtered output.
    ///
    /// # Arguments
    ///
    /// * `input` - The raw input sample to be filtered.
    ///
    /// # Returns
    ///
    /// The filtered output sample.
    fn calculate_output(&mut self, input: f64) -> f64 {
        let output = (self.b[0] / self.a[0]) * input
            + (self.b[1] / self.a[0]) * self.x[0]
            + (self.b[2] / self.a[0]) * self.x[1]
            - (self.a[1] / self.a[0]) * self.y[0]
            - (self.a[2] / self.a[0]) * self.y[1];

        // Update internal sample history
        self.x[1] = self.x[0];
        self.x[0] = input;
        self.y[1] = self.y[0];
        self.y[0] = output;

        output
    }
}
