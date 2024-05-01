use super::{FilterInstance, Statistics};
use std::collections::HashMap;

pub struct BandPassFilterConfig {
    pub f0: f64,
    pub fs: f64,
}

pub struct BandPassFilter {
    statistics: Statistics, // Include Statistics in the filter
    a: [f64; 3],
    b: [f64; 3],
    x: [f64; 2],
    y: [f64; 2],
}

impl BandPassFilter {
    // Constructor with Statistics initialization
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
            statistics: Statistics::new(),
            a: [a0, a1, a2],
            b: [b0, b1, b2],
            x: [0.0, 0.0],
            y: [0.0, 0.0],
        }
    }

    // Calculating output based on the input and updating the filter's internal state
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

impl FilterInstance for BandPassFilter {
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, filter_id: &str) {
        if let Some(&raw_sample) = results.get("global:raw_sample") {
            let filtered_sample = self.calculate_output(raw_sample);
            self.statistics.update_statistics(filtered_sample);

            // Update results with the filtered sample and its statistics
            results.insert(
                format!("filters:{}:filtered_sample", filter_id),
                filtered_sample,
            );
            results.insert(
                format!("filters:{}:z_score", filter_id),
                self.statistics.z_score,
            );
        }
    }
}
