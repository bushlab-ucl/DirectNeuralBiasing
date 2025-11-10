use super::detectors::DetectorInstance;
use super::filters::FilterInstance;
use super::triggers::TriggerInstance;

use serde::{Deserialize, Serialize};
use serde_yaml;
use std::collections::{HashMap, VecDeque};
// use std::time;

use colored::Colorize;
use std::sync::Arc;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

// Uncomment these imports as we'll need them for logging
use crate::utils::log::{
    generate_log_filename, log_config, log_to_file, log_trigger_event, log_verbose,
}; // Import new logging functions
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
// use rayon::prelude::*;
// use std::os::raw::c_void;

use crate::config::load_config;
use crate::visualization::{plotter::SharedPlotter, VisualizationData};

// -----------------------------------------------------------------------------
// RUST CORE LOGIC
// -----------------------------------------------------------------------------

// SIGNAL PROCESSOR COMPONENT --------------------------------------------------

// not used in this file, but kept for other files
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct SignalProcessorConfig {
    pub verbose: bool,
    pub fs: f64,
    pub channel: usize,
    pub enable_debug_logging: bool, // New field to control debug logging
    pub log_context_samples: Option<usize>, // Number of samples before/after to log (optional)
}

pub struct SignalProcessor {
    pub index: usize,
    pub filters: HashMap<String, Box<dyn FilterInstance>>,
    pub detectors: HashMap<String, Box<dyn DetectorInstance>>,
    pub triggers: HashMap<String, Box<dyn TriggerInstance>>,
    pub processor_config: SignalProcessorConfig, // Use the config from the main config struct
    pub results: HashMap<&'static str, f64>,
    pub keys: Keys, // Consider making Keys constants if they are fixed strings
    log_sender: Option<Sender<(Vec<HashMap<&'static str, f64>>, String)>>, // Channel to send logs to background thread (now with context)
    context_buffer: VecDeque<HashMap<&'static str, f64>>, // Ring buffer for context logging
    context_size: usize,                                  // Number of samples before/after to keep
    log_file_name: String,                                // Log file name for verbose logging
    visualization_plotter: Option<SharedPlotter>,
}

// Consider if Keys struct is necessary, or if constants are sufficient
pub struct Keys {
    global_index: &'static str,
    global_raw_sample: &'static str,
    global_channel: &'static str,
    global_timestamp_ms: &'static str,
}

impl SignalProcessor {
    /// Builds a new SignalProcessor instance from a configuration file.
    pub fn from_config_file(config_path: &str) -> Result<Self, String> {
        // Load the entire config from the file
        let config = load_config(config_path)?;

        // Generate timestamp for log filename to avoid overwriting previous sessions
        let log_file_name = generate_log_filename("trigger_debug", "log");

        // Log the current config to the log file
        if config.processor.enable_debug_logging {
            // Convert config back to YAML format for logging
            let config_yaml_result = serde_yaml::to_string(&config);
            let config_yaml = match config_yaml_result {
                Ok(yaml) => yaml,
                Err(e) => {
                    eprintln!("Failed to serialize config to YAML: {}", e);
                    format!("Failed to serialize config to YAML: {}", e)
                }
            };

            // Debug: Print to console as well
            eprintln!("Attempting to log config to logs/{}", log_file_name);

            match log_config(&log_file_name, config_path, &config_yaml) {
                Ok(_) => eprintln!("Successfully logged config to logs/{}", log_file_name),
                Err(e) => eprintln!("Failed to log config to file: {}", e),
            }
        }

        // Get context size from config or use default
        let context_size = config.processor.log_context_samples.unwrap_or(3);

        // Setup logging
        let log_sender = if config.processor.enable_debug_logging {
            // Set up logging thread only if debug logging is enabled
            let (tx, rx) = mpsc::channel();
            // We can keep setup_logging_thread as a private helper within the impl
            SignalProcessor::setup_logging_thread(rx, log_file_name.clone());
            Some(tx)
        } else {
            None
        };

        // NEW: Setup visualization if enabled
        let visualization_plotter = if config.visualization.enabled {
            use crate::visualization::plotter::create_shared_plotter;
            use crate::visualization::window::spawn_visualization_window;

            let plotter = create_shared_plotter(config.visualization.clone());

            // Spawn the visualization window in a separate thread
            let plotter_clone = Arc::clone(&plotter);
            spawn_visualization_window(plotter_clone, config.visualization.clone());

            Some(plotter)
        } else {
            None
        };

        let mut processor = SignalProcessor {
            index: 0,
            filters: HashMap::new(),
            detectors: HashMap::new(),
            triggers: HashMap::new(),
            processor_config: config.processor.clone(), // Clone the processor part of the config
            results: HashMap::with_capacity(32),
            keys: Keys {
                // Consider using constants instead of this struct
                global_index: "global:index",
                global_raw_sample: "global:raw_sample",
                global_channel: "global:channel",
                global_timestamp_ms: "global:timestamp_ms",
            },
            log_sender,
            context_buffer: VecDeque::with_capacity(context_size * 2 + 1),
            context_size,
            log_file_name,
            visualization_plotter,
        };
        // --- End of logic moved from the old `new` function ---

        // --- Start of logic moved from the old `from_config` function ---
        // Add all filters from config
        for filter_config in &config.filters.bandpass_filters {
            let filter = super::filters::bandpass::BandPassFilter::new(
                super::filters::bandpass::BandPassFilterConfig {
                    id: filter_config.id.clone(),
                    f_low: filter_config.f_low,
                    f_high: filter_config.f_high,
                },
                processor.processor_config.fs,
            );
            processor.add_filter(Box::new(filter));
        }

        // Add all detectors from config
        for detector_config in &config.detectors.wave_peak_detectors {
            let wave_detector = super::detectors::wave_peak::WavePeakDetector::new(
                super::detectors::wave_peak::WavePeakDetectorConfig {
                    id: detector_config.id.clone(),
                    filter_id: detector_config.filter_id.clone(),
                    z_score_threshold: detector_config.z_score_threshold,
                    sinusoidness_threshold: detector_config.sinusoidness_threshold,
                    check_sinusoidness: detector_config.check_sinusoidness,
                    wave_polarity: detector_config.wave_polarity.clone(),
                    min_wave_length_ms: detector_config.min_wave_length_ms,
                    max_wave_length_ms: detector_config.max_wave_length_ms,
                },
            );
            processor.add_detector(Box::new(wave_detector));
        }

        // Add all triggers from config
        for trigger_config in &config.triggers.pulse_triggers {
            let trigger = super::triggers::pulse::PulseTrigger::new(
                super::triggers::pulse::PulseTriggerConfig {
                    id: trigger_config.id.clone(),
                    activation_detector_id: trigger_config.activation_detector_id.clone(),
                    inhibition_detector_id: trigger_config.inhibition_detector_id.clone(),
                    inhibition_cooldown_ms: trigger_config.inhibition_cooldown_ms,
                    pulse_cooldown_ms: trigger_config.pulse_cooldown_ms,
                },
            );
            processor.add_trigger(Box::new(trigger));
        }
        // --- End of logic moved from the old `from_config` function ---

        Ok(processor)
    }

    // We keep setup_logging_thread as a private helper method
    fn setup_logging_thread(
        rx: Receiver<(Vec<HashMap<&'static str, f64>>, String)>,
        log_file_name: String,
    ) {
        thread::spawn(move || {
            // remove comments to overwrite logs on each load
            // // --- Call the new function to delete the old log file ---
            // if let Err(e) = crate::utils::log::delete_log_file(log_file_name) {
            //     eprintln!(
            //         "{}",
            //         format!(
            //             "Warning: Failed to delete old log file '{}': {}",
            //             log_file_name, e
            //         )
            //         .yellow()
            //     );
            //     // Continue execution even if deletion failed, just warn the user.
            // }
            // // --- End of call ---

            let _ = log_to_file(&log_file_name, "Signal processor trigger logging started");

            while let Ok((context_results, trigger_id)) = rx.recv() {
                // Log the trigger event using the new function
                if let Err(e) = log_trigger_event(&log_file_name, &trigger_id, &context_results) {
                    eprintln!("{}", format!("Failed to log trigger event: {}", e).red());
                }
            }
            // Log shutdown message when sender is dropped and channel is empty
            let _ = log_to_file(
                &log_file_name,
                "Signal processor trigger logging shut down.",
            );
        });
    }

    /// Logs a message to both terminal and file when verbose logging is enabled
    fn log_verbose(&self, message: &str) {
        if let Err(e) = log_verbose(
            &self.log_file_name,
            message,
            self.processor_config.enable_debug_logging,
        ) {
            eprintln!("Failed to log verbose message: {}", e);
        }
    }

    /// Public method to log messages from external code (e.g., C++)
    #[allow(dead_code)]
    pub fn log_message(&self, message: &str) {
        if let Err(e) = log_verbose(
            &self.log_file_name,
            message,
            self.processor_config.enable_debug_logging,
        ) {
            eprintln!("Failed to log message from external code: {}", e);
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
            // Use the processor_config for verbose checking if needed
            if self.processor_config.verbose {
                self.log_verbose(
                    &format!(
                        "Warning: Detector '{}' references non-existent filter ID: {}",
                        id, filter_id
                    )
                    .yellow()
                    .to_string(),
                );
            }
            // Decide if this should be a panic or just a warning + skipping
            // For now, let's keep the panic as it indicates a critical config error
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
            if self.processor_config.verbose {
                self.log_verbose(
                    &format!(
                        "Warning: Trigger '{}' references non-existent activation detector ID: {}",
                        id, activation_detector_id
                    )
                    .yellow()
                    .to_string(),
                );
            }
            panic!(
                "Trigger references non-existent activation detector ID: {}",
                activation_detector_id
            );
        }

        // Check if the inhibition detector ID is valid (if not empty)
        if !inhibition_detector_id.is_empty()
            && !self.detectors.contains_key(&inhibition_detector_id)
        {
            if self.processor_config.verbose {
                self.log_verbose(
                    &format!(
                        "Warning: Trigger '{}' references non-existent inhibition detector ID: {}",
                        id, inhibition_detector_id
                    )
                    .yellow()
                    .to_string(),
                );
            }
            panic!(
                "Trigger references non-existent inhibition detector ID: {}",
                inhibition_detector_id
            );
        }
        // Handle the case where inhibition_detector_id is empty string, which is valid
        if inhibition_detector_id.is_empty() {
            if self.processor_config.verbose {
                self.log_verbose(
                    &format!("Trigger '{}' has no inhibition detector.", id)
                        .blue()
                        .to_string(),
                );
            }
        }

        self.triggers.insert(id, trigger);
    }

    // Extract context around the current sample for logging
    fn extract_context_for_logging(&self) -> Vec<HashMap<&'static str, f64>> {
        // Return the collected context samples
        self.context_buffer.iter().cloned().collect()
    }

    // Enhanced logging method that sends context
    fn send_log_event_with_context(
        &self,
        context: Vec<HashMap<&'static str, f64>>,
        trigger_id: String,
    ) {
        if let Some(sender) = &self.log_sender {
            if let Err(e) = sender.send((context, trigger_id)) {
                eprintln!("{}", format!("Failed to send log event: {}", e).red());
            }
        }
    }

    // NEW: Method to send data to visualization
    fn update_visualization(&self) {
        if let Some(ref plotter) = self.visualization_plotter {
            // Extract raw sample
            let raw_sample = self
                .results
                .get("global:raw_sample")
                .copied()
                .unwrap_or(0.0);
            let timestamp = self
                .results
                .get("global:timestamp_ms")
                .copied()
                .unwrap_or(0.0);

            // Extract filtered samples
            let mut filtered_samples = Vec::new();
            for (filter_id, _) in &self.filters {
                let key = format!("filters:{}:filtered_sample", filter_id);
                if let Some(&value) = self.results.get(key.as_str()) {
                    filtered_samples.push((filter_id.clone(), value));
                }
            }

            // Extract detections
            let mut detections = Vec::new();
            for (detector_id, _) in &self.detectors {
                let key = format!("detectors:{}:detected", detector_id);
                if let Some(&detected) = self.results.get(key.as_str()) {
                    detections.push((detector_id.clone(), detected > 0.0));
                }
            }

            let vis_data = VisualizationData {
                timestamp,
                raw_sample,
                filtered_samples,
                detections,
            };

            if let Ok(mut plotter_guard) = plotter.lock() {
                plotter_guard.add_data(vis_data);
            }
        }
    }

    // Process a Vec of raw samples - chunk with defined length
    pub fn run_chunk(
        &mut self,
        raw_samples: Vec<f64>,
    ) -> (Vec<HashMap<&'static str, f64>>, Option<f64>) {
        let mut output = Vec::with_capacity(raw_samples.len());
        let mut trigger_timestamp_option = None;
        let start_time_whole = Instant::now(); // Start timer before analysis

        // Create a vector to collect trigger events with context
        let mut trigger_events_with_context = Vec::new();
        let mut error_messages = Vec::new(); // Collect error messages to log after the loop

        for sample in raw_samples {
            // Reset and update globals
            self.results.clear();
            self.results
                .insert(&self.keys.global_index, self.index as f64);
            self.results.insert(&self.keys.global_raw_sample, sample);
            self.results.insert(
                &self.keys.global_channel,
                self.processor_config.channel as f64,
            ); // Use processor_config
            self.results.insert(
                &self.keys.global_timestamp_ms,
                self.index as f64 / self.processor_config.fs * 1000.0, // Correct conversion to ms (divide by fs, multiply by 1000)
            );

            // Filters process the sample
            for (_id, filter) in self.filters.iter_mut() {
                filter.process_sample(&self.processor_config, &mut self.results);
                // Use processor_config
            }

            // Detectors process the filtered results
            for (_id, detector) in self.detectors.iter_mut() {
                detector.process_sample(&self.processor_config, &mut self.results, self.index);
                // Use processor_config
            }

            // Add current results to context buffer (after all processing is done for this sample)
            self.context_buffer.push_back(self.results.clone());

            // Maintain buffer size (keep only what we need for context)
            while self.context_buffer.len() > (self.context_size * 2 + 1) {
                self.context_buffer.pop_front();
            }

            // Triggers evaluate based on detector outputs
            for (id, trigger) in self.triggers.iter_mut() {
                trigger.evaluate(&self.processor_config, &mut self.results); // Use processor_config

                // Check if the trigger has been activated
                let trigger_key = format!("triggers:{}:triggered", id);
                let triggered = self
                    .results
                    .get(trigger_key.as_str()) // Use as_str() to get the key without leaking
                    .cloned()
                    .unwrap_or(0.0)
                    > 0.0;

                if triggered {
                    let now = SystemTime::now();

                    let trigger_index_key = format!("triggers:{}:trigger_index", id);
                    let trigger_index = self
                        .results
                        .get(trigger_index_key.as_str()) // Use as_str()
                        .cloned()
                        .unwrap_or(0.0) as usize;

                    // Verify the trigger index is ahead of or at the current index
                    // A trigger occurring at the current index is valid.
                    if trigger_index < self.index {
                        if self.processor_config.verbose {
                            error_messages.push(format!("Error: Trigger index ({}) for trigger '{}' is behind the current index ({})!",
                                   trigger_index, id, self.index));
                        }
                        continue; // Skip processing for this trigger instance
                    }

                    // Compute the relative time offset as a Duration
                    let sample_diff = trigger_index as isize - self.index as isize;
                    let time_offset =
                        Duration::from_secs_f64(sample_diff as f64 / self.processor_config.fs); // Use processor_config

                    // Add the relative time offset to the current UNIX time
                    let future_trigger_timestamp = now + time_offset;

                    // Convert SystemTime to UNIX timestamp (f64) for c++ compatibility
                    let unix_timestamp = future_trigger_timestamp
                        .duration_since(UNIX_EPOCH)
                        .expect("Time went backwards") // This should generally not happen with SystemTime::now()
                        .as_secs_f64();

                    // If debug logging is enabled, collect the trigger ID for later context extraction
                    if self.processor_config.enable_debug_logging {
                        // Store just the trigger ID, we'll extract context after the loop
                        trigger_events_with_context.push((Vec::new(), id.clone()));
                        // Temporary empty Vec
                    }

                    // Update the trigger timestamp option
                    trigger_timestamp_option = Some(unix_timestamp);

                    // Optional: Break after the first trigger if you only want one trigger per chunk
                    // break;
                }
            }

            // Extract context for any triggered events (after the mutable borrow is done)
            if self.processor_config.enable_debug_logging && !trigger_events_with_context.is_empty()
            {
                let context = self.extract_context_for_logging();
                // Update all trigger events with the same context (since they all occur at the same sample)
                for (context_ref, _) in trigger_events_with_context.iter_mut() {
                    *context_ref = context.clone();
                }
            }

            // NEW: Update visualization after all processing for this sample
            self.update_visualization();

            output.push(self.results.clone());
            self.index += 1;
        }

        // Now log all collected trigger events with context outside the mutable borrow scope
        for (context, trigger_id) in trigger_events_with_context {
            self.send_log_event_with_context(context, trigger_id);
        }

        // Log any error messages collected during processing
        for error_msg in error_messages {
            self.log_verbose(&error_msg.red().to_string());
        }

        // debug print timing (conditional on verbose flag)
        if self.processor_config.verbose {
            // Use processor_config
            let duration_whole = start_time_whole.elapsed();
            self.log_verbose(
                &format!("Processed chunk in {:?}", duration_whole)
                    .blue()
                    .to_string(),
            );

            // debug print trigger timestamp option
            self.log_verbose(
                &format!("Trigger timestamp option: {:?}", trigger_timestamp_option)
                    .color(if trigger_timestamp_option.is_some() {
                        "green"
                    } else {
                        "red"
                    })
                    .to_string(),
            );

            // debug print output length
            self.log_verbose(
                &format!("Output length: {:?}", output.len())
                    .color("yellow")
                    .to_string(),
            );
        }

        return (output, trigger_timestamp_option);
    }
}

// Potential constants for Keys if you remove the Keys struct
/*
const GLOBAL_INDEX_KEY: &str = "global:index";
const GLOBAL_RAW_SAMPLE_KEY: &str = "global:raw_sample";
const GLOBAL_CHANNEL_KEY: &str = "global:channel";
const GLOBAL_TIMESTAMP_MS_KEY: &str = "global:timestamp_ms";
*/
