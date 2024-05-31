use super::detectors::DetectorInstance;
use super::filters::FilterInstance;
use super::triggers::TriggerInstance;

use std::collections::HashMap;

use std::time::{Duration, Instant};

// use crate::utils::log::log_to_file;
// use rayon::prelude::*;
// use std::os::raw::c_void;

// -----------------------------------------------------------------------------
// RUST CORE LOGIC
// -----------------------------------------------------------------------------

// SIGNAL PROCESSOR COMPONENT --------------------------------------------------

pub struct SignalProcessorConfig {
    pub verbose: bool,
}

pub struct SignalProcessor {
    pub index: usize,
    pub filters: HashMap<String, Box<dyn FilterInstance>>,
    pub detectors: HashMap<String, Box<dyn DetectorInstance>>,
    pub triggers: HashMap<String, Box<dyn TriggerInstance>>,
    pub config: SignalProcessorConfig,
    pub results: HashMap<String, f64>,
    pub keys: Keys,
}

pub struct Keys {
    global_index: String,
    global_raw_sample: String,
}

impl SignalProcessor {
    pub fn new(config: SignalProcessorConfig) -> Self {
        SignalProcessor {
            index: 0,
            filters: HashMap::new(),
            detectors: HashMap::new(),
            triggers: HashMap::new(),
            config,
            results: HashMap::new(),
            keys: Keys {
                global_index: "global:index".to_string(),
                global_raw_sample: "global:raw_sample".to_string(),
            },
        }
    }

    pub fn add_filter(&mut self, filter: Box<dyn FilterInstance>) {
        let id = filter.id().to_string();
        self.filters.insert(id, filter);
    }

    pub fn add_detector(&mut self, detector: Box<dyn DetectorInstance>) {
        let id = detector.id().to_string();
        let filter_id = detector.filter_id().to_string();

        // Check if the detector references a valid filter ID
        if !self.filters.contains_key(&filter_id) {
            panic!("Detector references non-existent filter ID: {}", filter_id);
        }

        self.detectors.insert(id, detector);
    }

    pub fn add_trigger(&mut self, trigger: Box<dyn TriggerInstance>) {
        let id = trigger.id().to_string();
        let activation_detector_id = trigger.activation_detector_id();
        let inhibition_detector_id = trigger.inhibition_detector_id();

        // Check if the activation detector ID is valid
        if !self.detectors.contains_key(&activation_detector_id) {
            panic!(
                "Trigger references non-existent activation detector ID: {}",
                activation_detector_id
            );
        }

        // Check if the inhibition detector ID is valid
        if !self.detectors.contains_key(&inhibition_detector_id) {
            panic!(
                "Trigger references non-existent inhibition detector ID: {}",
                inhibition_detector_id
            );
        }

        self.triggers.insert(id, trigger);
    }

    // Process a Vec of raw samples
    pub fn run(&mut self, raw_samples: Vec<f64>) -> Vec<HashMap<String, f64>> {
        let mut output = Vec::new();
        let keys = &self.keys;

        for sample in raw_samples {
            // let start_time_whole = Instant::now(); // Start timer before analysis

            // Reset and update globals
            self.results.clear();
            self.results
                .insert(keys.global_index.clone(), self.index as f64);
            self.results.insert(keys.global_raw_sample.clone(), sample);

            // Filters process the sample
            // let start_time = Instant::now(); // Start timer before analysis
            for (_id, filter) in self.filters.iter_mut() {
                filter.process_sample(&self.config, &mut self.results);
            }
            // let duration = start_time.elapsed();
            // println!("Filters ran  in {:?}", duration); // Timing the analysis phase only

            // Detectors process the filtered results
            // let start_time = Instant::now(); // Start timer before analysis
            for (_id, detector) in self.detectors.iter_mut() {
                detector.process_sample(&self.config, &mut self.results, self.index);
            }
            // let duration = start_time.elapsed();
            // println!("Detectors ran  in {:?}", duration); // Timing the analysis phase only

            // Triggers evaluate based on detector outputs
            // let start_time = Instant::now(); // Start timer before analysis
            for (_id, trigger) in self.triggers.iter_mut() {
                trigger.evaluate(&self.config, &mut self.results);
            }
            // let duration = start_time.elapsed();
            // println!("Triggers ran  in {:?}", duration); // Timing the analysis phase only

            output.push(self.results.clone());

            self.index += 1;

            // let duration_whole = start_time_whole.elapsed();
            // println!("Whole block ran  in {:?}", duration_whole); // Timing the analysis phase only
        }

        output
    }
}
