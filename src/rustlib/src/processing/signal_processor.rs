use super::detectors::DetectorInstance;
use super::filters::FilterInstance;
use super::triggers::TriggerInstance;

use std::collections::HashMap;
// use std::time;

use colored::Colorize;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

// Uncomment these imports as we'll need them for logging
use crate::utils::log::log_to_file;
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
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
    pub enable_debug_logging: bool, // New field to control debug logging
}

pub struct SignalProcessor {
    pub index: usize,
    pub filters: HashMap<String, Box<dyn FilterInstance>>,
    pub detectors: HashMap<String, Box<dyn DetectorInstance>>,
    pub triggers: HashMap<String, Box<dyn TriggerInstance>>,
    pub config: SignalProcessorConfig,
    pub results: HashMap<&'static str, f64>,
    pub keys: Keys,
    log_sender: Option<Sender<(HashMap<&'static str, f64>, String)>>, // Channel to send logs to background thread
}

pub struct Keys {
    global_index: &'static str,
    global_raw_sample: &'static str,
    global_channel: &'static str,
    global_timestamp_ms: &'static str,
}

impl SignalProcessor {
    pub fn new(config: SignalProcessorConfig) -> Self {
        let log_sender = if config.enable_debug_logging {
            // Set up logging thread only if debug logging is enabled
            let (tx, rx) = mpsc::channel();
            SignalProcessor::setup_logging_thread(rx);
            Some(tx)
        } else {
            None
        };

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
            log_sender,
        }
    }

    // New method to set up the logging thread
    fn setup_logging_thread(rx: Receiver<(HashMap<&'static str, f64>, String)>) {
        thread::spawn(move || {
            // Create an initial log entry to show the logging system is active
            let _ = log_to_file(
                "trigger_debug.log", 
                "Signal processor trigger logging started"
            );
            
            while let Ok((results, trigger_id)) = rx.recv() {
                // Get current timestamp for the log
                let timestamp = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or(Duration::from_secs(0))
                    .as_secs_f64();
                
                // Format the trigger event information
                let mut log_entry = format!(
                    "TRIGGER EVENT [{}]\n", 
                    timestamp
                );
                
                // Add trigger ID
                log_entry.push_str(&format!("Trigger ID: {}\n\n", trigger_id));
                
                // Add all results values in a readable format
                log_entry.push_str("RESULTS CONTEXT:\n");
                log_entry.push_str("----------------\n");
                
                // Create sorted list of keys for consistent output
                let mut keys: Vec<&&'static str> = results.keys().collect();
                keys.sort();
                
                for &key in keys {
                    if let Some(value) = results.get(key) {
                        log_entry.push_str(&format!("{} = {}\n", key, value));
                    }
                }
                
                // Log the event to file
                if let Err(e) = log_to_file("trigger_debug.log", &log_entry) {
                    eprintln!("{}", format!("Failed to log trigger event: {}", e).red());
                }
            }
        });
    }

    // New method to log trigger events
    fn log_trigger_event(&self, trigger_id: String) {
        if let Some(sender) = &self.log_sender {
            if let Err(e) = sender.send((self.results.clone(), trigger_id)) {
                eprintln!("{}", format!("Failed to send log event: {}", e).red());
            }
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
        let start_time_whole = Instant::now(); // Start timer before analysis
        
        // Create a vector to collect trigger events
        let mut trigger_events = Vec::new();

        for sample in raw_samples {
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
            for (_id, filter) in self.filters.iter_mut() {
                filter.process_sample(&self.config, &mut self.results);
            }

            // Detectors process the filtered results
            for (_id, detector) in self.detectors.iter_mut() {
                detector.process_sample(&self.config, &mut self.results, self.index);
            }

            // Triggers evaluate based on detector outputs
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
                    
                    // If debug logging is enabled, collect the trigger event info for later logging
                    if self.config.enable_debug_logging {
                        // Clone both results and trigger ID for the event log
                        trigger_events.push((self.results.clone(), id.clone()));
                    }
                    
                    // Update the trigger timestamp
                    trigger_timestamp_option = Some(unix_timestamp);
                }
            }

            output.push(self.results.clone());
            self.index += 1;
        }

        // Now log all collected trigger events outside the mutable borrow scope
        if self.config.enable_debug_logging {
            for (results, trigger_id) in trigger_events {
                if let Some(sender) = &self.log_sender {
                    if let Err(e) = sender.send((results, trigger_id)) {
                        eprintln!("{}", format!("Failed to send log event: {}", e).red());
                    }
                }
            }
        }

        // debug print timing
        let duration_whole = start_time_whole.elapsed();
        eprintln!(
            "{}",
            format!("Processed chunk in {:?}", duration_whole).blue()
        );

        // debug print trigger timestamp option
        eprintln!(
            "{}",
            format!("Trigger timestamp option: {:?}", trigger_timestamp_option).color(
                if trigger_timestamp_option.is_some() {
                    "green"
                } else {
                    "red"
                }
            )
        );

        // debug print output length
        eprintln!(
            "{}",
            format!("Output length: {:?}", output.len()).color("yellow")
        );

        return (output, trigger_timestamp_option);
    }
}
