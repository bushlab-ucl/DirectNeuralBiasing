use super::FilterInstance;
use crate::processing::signal_processor::SignalProcessorConfig;

use std::collections::HashMap;
use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct BandPassFilterConfig {
    pub id: String,
    pub f_low: f64,
    pub f_high: f64,
}

pub struct BandPassFilter {
    config: BandPassFilterConfig,
    high_pass: SecondOrderFilter,
    low_pass: SecondOrderFilter,
    keys: Keys,
}

struct SecondOrderFilter {
    a: [f64; 3],
    b: [f64; 3],
    x: [f64; 2],
    y: [f64; 2],
}

impl SecondOrderFilter {
    pub fn new(f0: f64, fs: f64, filter_type: &str) -> Self {
        let q = (2.0f64).sqrt() / 2.0; // Example for a Butterworth filter
        let omega = 2.0 * std::f64::consts::PI * f0 / fs;
        let alpha = f64::sin(omega) / (2.0 * q);

        let (b0, b1, b2, a0, a1, a2) = match filter_type {
            "high" => (
                (1.0 + f64::cos(omega)) / 2.0,
                -(1.0 + f64::cos(omega)),
                (1.0 + f64::cos(omega)) / 2.0,
                1.0 + alpha,
                -2.0 * f64::cos(omega),
                1.0 - alpha,
            ),
            "low" => (
                (1.0 - f64::cos(omega)) / 2.0,
                1.0 - f64::cos(omega),
                (1.0 - f64::cos(omega)) / 2.0,
                1.0 + alpha,
                -2.0 * f64::cos(omega),
                1.0 - alpha,
            ),
            _ => panic!("Unsupported filter type"),
        };

        SecondOrderFilter {
            a: [a0, a1, a2],
            b: [b0, b1, b2],
            x: [0.0, 0.0],
            y: [0.0, 0.0],
        }
    }

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

pub struct Keys {
    filtered_sample: &'static str,
}

impl BandPassFilter {
    // Constructor with initialization for high-pass and low-pass filters
    pub fn new(config: BandPassFilterConfig, fs: f64) -> Self {
        let high_pass = SecondOrderFilter::new(config.f_low, fs, "high");
        let low_pass = SecondOrderFilter::new(config.f_high, fs, "low");
        let keys = Keys {
            filtered_sample: Box::leak(
                format!("filters:{}:filtered_sample", config.id).into_boxed_str(),
            ),
        };

        BandPassFilter {
            config,
            high_pass,
            low_pass,
            keys,
        }
    }
}

impl FilterInstance for BandPassFilter {
    fn id(&self) -> &str {
        &self.config.id
    }

    fn process_sample(
        &mut self,
        _global_config: &SignalProcessorConfig,
        results: &mut HashMap<&'static str, f64>,
    ) {
        if let Some(&raw_sample) = results.get("global:raw_sample") {
            // Apply high-pass filter first
            let high_pass_output = self.high_pass.calculate_output(raw_sample);
            // Apply low-pass filter to the output of the high-pass filter
            let filtered_sample = self.low_pass.calculate_output(high_pass_output);

            results.insert(self.keys.filtered_sample, filtered_sample);
        }
    }
}
