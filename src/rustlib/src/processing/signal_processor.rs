use super::detectors::DetectorInstance;
use super::filters::FilterInstance;
use super::triggers::TriggerInstance;

use std::collections::HashMap;
// use std::time;

// use std::time::{Instant};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

// use crate::utils::log::log_to_file;
// use rayon::prelude::*;
// use std::os::raw::c_void;

// -----------------------------------------------------------------------------
// RUST CORE LOGIC
// -----------------------------------------------------------------------------

// SIGNAL PROCESSOR COMPONENT --------------------------------------------------

pub struct SignalProcessorConfig {
    pub verbose: bool,
    pub fs: f64,
    pub channel: usize,
}

pub struct SignalProcessor {
    pub index: usize,
    pub filters: HashMap<String, Box<dyn FilterInstance>>,
    pub detectors: HashMap<String, Box<dyn DetectorInstance>>,
    pub triggers: HashMap<String, Box<dyn TriggerInstance>>,
    pub config: SignalProcessorConfig,
    pub results: HashMap<&'static str, f64>,
    pub keys: Keys,
}

pub struct Keys {
    global_index: &'static str,
    global_raw_sample: &'static str,
    global_channel: &'static str,
    global_timestamp_ms: &'static str,
}

impl SignalProcessor {
    pub fn new(config: SignalProcessorConfig) -> Self {
        SignalProcessor {
            index: 0,
            filters: HashMap::new(),
            detectors: HashMap::new(),
            triggers: HashMap::new(),
            config,
            results: HashMap::with_capacity(32),
            keys: Keys {
                global_index: "global:index",
                global_raw_sample: "global:raw_sample",
                global_channel: "global:channel",
                global_timestamp_ms: "global:timestamp_ms",
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

    // Process a Vec of raw samples - chunk with defined length
    pub fn run_chunk(
        &mut self,
        raw_samples: Vec<f64>,
    ) -> (Vec<HashMap<&'static str, f64>>, Option<f64>) {
        let mut output = Vec::with_capacity(raw_samples.len());
        let mut trigger_timestamp_option = None;

        for sample in raw_samples {
            // let start_time_whole = Instant::now(); // Start timer before analysis

            // Reset and update globals
            self.results.clear();
            self.results
                .insert(&self.keys.global_index, self.index as f64);
            self.results.insert(&self.keys.global_raw_sample, sample);
            self.results
                .insert(&self.keys.global_channel, self.config.channel as f64);
            self.results.insert(
                &self.keys.global_timestamp_ms,
                self.index as f64 / self.config.fs * 10.0, // convert from index to ms
            );

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
            for (id, trigger) in self.triggers.iter_mut() {
                trigger.evaluate(&self.config, &mut self.results);

                // Check if the trigger has been activated
                let triggered = self
                    .results
                    .get(Box::leak(
                        format!("triggers:{}:triggered", id).into_boxed_str(),
                    ))
                    .cloned()
                    .unwrap_or(0.0)
                    > 0.0;

                if triggered {
                    let now = SystemTime::now();

                    let trigger_index = self
                        .results
                        .get(Box::leak(
                            format!("triggers:{}:trigger_index", id).into_boxed_str(),
                        ))
                        .cloned()
                        .unwrap_or(0.0) as usize;

                    // Verify the trigger index is ahead of the current index
                    if trigger_index < self.index {
                        eprintln!(
                            "Error: Trigger index ({}) is behind the current index ({})!",
                            trigger_index, self.index
                        );
                        continue; // Skip processing for this trigger
                    }

                    // Compute the relative time offset as a Duration
                    let sample_diff = trigger_index as isize - self.index as isize;
                    let time_offset = Duration::from_secs_f64(sample_diff as f64 / self.config.fs);

                    // Add the relative time offset to the current UNIX time
                    let future_trigger_timestamp = now + time_offset;

                    // Convert SystemTime to UNIX timestamp (f64) for c++ compatibility
                    let unix_timestamp = future_trigger_timestamp
                        .duration_since(UNIX_EPOCH)
                        .expect("Time went backwards")
                        .as_secs_f64();

                    // Update the trigger timestamp
                    trigger_timestamp_option = Some(unix_timestamp);

                    // //debug, print now time from above
                    // println!("Now time: {:?}", now);

                    // // Debugging: print the computed future timestamp
                    // println!(
                    //     "Future trigger timestamp: {:?} (Relative offset: {:?})",
                    //     future_trigger_timestamp, time_offset
                    // );
                }
            }
            // let duration = start_time.elapsed();
            // println!("Triggers ran  in {:?}", duration); // Timing the analysis phase only

            output.push(self.results.clone());

            self.index += 1;

            // let duration_whole = start_time_whole.elapsed();
            // println!("Whole block ran  in {:?}", duration_whole); // Timing the analysis phase only
        }

        return (output, trigger_timestamp_option);
    }
}
