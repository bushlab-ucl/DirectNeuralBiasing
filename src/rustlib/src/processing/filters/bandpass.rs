use super::FilterInstance;
use crate::processing::signal_processor::SignalProcessorConfig;
use std::collections::HashMap;

pub struct BandPassFilterConfig {
    pub id: String,
    pub f0: f64,
    pub fs: f64,
}

pub struct BandPassFilter {
    config: BandPassFilterConfig,
    a: [f64; 3],
    b: [f64; 3],
    x: [f64; 2],
    y: [f64; 2],
}

impl FilterInstance for BandPassFilter {
    fn id(&self) -> &str {
        &self.config.id
    }

    fn process_sample(
        &mut self,
        _global_config: &SignalProcessorConfig,
        results: &mut HashMap<String, f64>,
    ) {
        if let Some(&raw_sample) = results.get("global:raw_sample") {
            let filtered_sample = self.calculate_output(raw_sample);
            results.insert(
                format!("filters:{}:filtered_sample", self.config.id),
                filtered_sample,
            );
        }
    }
}

impl BandPassFilter {
    // Constructor with Statistics initialization
    pub fn new(config: BandPassFilterConfig) -> Self {
        let adjusted_fs = config.fs;

        let q = (2.0f64).sqrt() / 2.0; // Example for a Butterworth filter
        let omega = 2.0 * std::f64::consts::PI * config.f0 / adjusted_fs;
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
