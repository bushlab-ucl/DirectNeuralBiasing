use super::detectors::DetectorInstance;
use super::filters::FilterInstance;
use super::triggers::TriggerInstance;

use std::collections::HashMap;

// use crate::utils::log::log_to_file;
// use rayon::prelude::*;
// use std::os::raw::c_void;

// -----------------------------------------------------------------------------
// RUST CORE LOGIC
// -----------------------------------------------------------------------------

// SIGNAL PROCESSOR COMPONENT --------------------------------------------------

pub struct SignalProcessorConfig {
    pub verbose: bool,
    pub log_to_file: bool,
    pub downsample_rate: usize,
}

pub struct SignalProcessor {
    pub index: usize,
    pub sample_count: usize,
    pub filters: HashMap<String, Box<dyn FilterInstance>>,
    pub detectors: HashMap<String, Box<dyn DetectorInstance>>,
    pub triggers: HashMap<String, Box<dyn TriggerInstance>>,
    pub config: SignalProcessorConfig,
    pub results: HashMap<String, f64>,
}

impl SignalProcessor {
    pub fn new(config: SignalProcessorConfig) -> Self {
        SignalProcessor {
            index: 0,
            sample_count: 0,
            filters: HashMap::new(),
            detectors: HashMap::new(),
            triggers: HashMap::new(),
            config,
            results: HashMap::new(),
        }
    }

    pub fn add_filter(&mut self, filter: Box<dyn FilterInstance>) {
        let id = filter.id().to_string();
        self.filters.insert(id, filter);
    }

    pub fn add_detector(&mut self, detector: Box<dyn DetectorInstance>) {
        let id = detector.id().to_string();
        self.detectors.insert(id, detector);
    }

    pub fn add_trigger(&mut self, trigger: Box<dyn TriggerInstance>) {
        let id = trigger.id().to_string();
        self.triggers.insert(id, trigger);
    }

    // Process a Vec of raw samples
    pub fn run(&mut self, raw_samples: Vec<f64>) -> Vec<HashMap<String, f64>> {
        let mut output = Vec::new();

        for sample in raw_samples {
            if self.sample_count % self.config.downsample_rate != 0 {
                continue;
            }

            // Reset and update globals
            self.results.clear();
            self.results
                .insert("global:index".to_string(), self.index as f64);
            self.results.insert("global:raw_sample".to_string(), sample);

            // Filters process the sample
            for (id, filter) in self.filters.iter_mut() {
                filter.process_sample(&mut self.results, id);
            }

            // Detectors process the filtered results
            for (id, detector) in self.detectors.iter_mut() {
                detector.process_sample(&mut self.results, self.index, id);
            }

            // Triggers evaluate based on detector outputs
            for (id, trigger) in self.triggers.iter_mut() {
                trigger.evaluate(&mut self.results, id);
            }

            output.push(self.results.clone());

            self.index += 1;
            self.sample_count += 1;
        }

        output
    }
}
