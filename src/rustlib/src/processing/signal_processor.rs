use super::detectors::DetectorInstance;
use super::filters::FilterInstance;
use super::triggers::TriggerInstance;

use super::detectors::threshold::{ThresholdDetector, ThresholdDetectorConfig};
use super::filters::bandpass::{BandPassFilter, BandPassFilterConfig};
use super::triggers::pulse::{PulseTrigger, PulseTriggerConfig};

// use crate::utils::log::log_to_file;
// use rayon::prelude::*;
use std::collections::HashMap;

use pyo3::prelude::*;
use std::time::Duration;
// use std::os::raw::c_void;

// -----------------------------------------------------------------------------
// RUST CORE LOGIC
// -----------------------------------------------------------------------------

// SIGNAL PROCESSOR COMPONENT --------------------------------------------------

pub struct SignalProcessorConfig {
    pub logging: bool,
    pub downsampling_rate: usize,
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
            self.index += 1;
            self.sample_count += 1;

            if self.sample_count % self.config.downsampling_rate != 0 {
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
        }

        output
    }
}

// -----------------------------------------------------------------------------
// PY03 PYTHON LOGIC
// -----------------------------------------------------------------------------

#[pyclass]
struct PySignalProcessor {
    processor: SignalProcessor,
}

#[pymethods]
impl PySignalProcessor {
    #[new]
    pub fn new(logging: bool, downsampling_rate: usize) -> Self {
        let config = SignalProcessorConfig {
            logging,
            downsampling_rate,
        };
        PySignalProcessor {
            processor: SignalProcessor::new(config),
        }
    }

    pub fn add_filter(&mut self, id: String, f0: f64, fs: f64) {
        let config = BandPassFilterConfig { id, f0, fs };
        let filter = BandPassFilter::new(config);
        self.processor.add_filter(Box::new(filter));
    }

    pub fn add_threshold_detector(
        &mut self,
        id: String,
        filter_id: String,
        threshold: f64,
        buffer_size: usize,
        sensitivity: f64,
    ) {
        let config = ThresholdDetectorConfig {
            id,
            filter_id,
            threshold,
            buffer_size,
            sensitivity,
        };
        let detector = ThresholdDetector::new(config);
        self.processor.add_detector(Box::new(detector));
    }

    pub fn add_pulse_trigger(
        &mut self,
        id: String,
        activation_detector_id: String,
        inhibition_detector_id: String,
        activation_cooldown: usize,
        inhibition_cooldown: usize,
    ) {
        let config = PulseTriggerConfig {
            id,
            activation_detector_id,
            inhibition_detector_id,
            activation_cooldown: Duration::from_secs(activation_cooldown as u64),
            inhibition_cooldown: Duration::from_secs(inhibition_cooldown as u64),
        };
        let trigger = PulseTrigger::new(config);
        self.processor.add_trigger(Box::new(trigger));
    }

    pub fn run(&mut self, data: Vec<f64>) -> Vec<HashMap<String, f64>> {
        self.processor.run(data)
    }
}

/// A Python module implemented in Rust.
#[pymodule]
fn direct_neural_biasing(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySignalProcessor>()?;

    Ok(())
}

// // -----------------------------------------------------------------------------
// // C++ FFI LOGIC
// // -----------------------------------------------------------------------------

// #[no_mangle]
// pub extern "C" fn create_filter(
//     f0_l: f64,
//     f0_h: f64,
//     fs: f64,
//     min_threshold_signal: f64,
//     max_threshold_signal: f64,
//     refractory_period: usize,
//     delay_to_up_state: usize,
//     threshold_sinusoid: f64,
//     logging: bool,
// ) -> *mut c_void {
//     let bounds: Vec<f64> = vec![f0_l, f0_h];
//     let filter = BandPassFilter::with_bounds(bounds, fs);
//     let state = Filter {
//         filter,
//         sum: 0.0,
//         count: 0,
//         min_threshold_signal,
//         max_threshold_signal,
//         mean: 0.0,
//         sum_of_squares: 0.0,
//         std_dev: 1.0,
//         filtered_sample: 0.0,
//         prev_sample: 0.0,
//         samples_since_zero_crossing: 0,
//         current_index: 0,
//         ongoing_wave: Vec::new(),
//         ongoing_wave_idx: Vec::new(),
//         detected_waves_idx: Vec::new(),
//         refractory_period,
//         refractory_samples_to_skip: 0,
//         delay_to_up_state,
//         absolute_min_threshold: 0.0,
//         absolute_max_threshold: 0.0,
//         threshold_sinusoid,
//         logging,
//     };
//     let boxed_state = Box::new(state);
//     Box::into_raw(boxed_state) as *mut c_void
// }

// #[no_mangle]
// pub extern "C" fn delete_filter(filter_ptr: *mut c_void) {
//     if filter_ptr.is_null() {
//         return;
//     }
//     unsafe {
//         drop(Box::from_raw(filter_ptr as *mut Filter));
//     }
// }

// #[no_mangle]
// pub extern "C" fn process_single_sample(filter_ptr: *mut c_void, sample: f64) -> bool {
//     if filter_ptr.is_null() {
//         return false;
//     }
//     let state = unsafe { &mut *(filter_ptr as *mut Filter) };

//     state.process_sample(sample);
//     // let z_score = state.calculate_z_score();

//     let above_min_threshold = state.filtered_sample > state.min_threshold_signal;
//     let below_max_threshold = state.filtered_sample < state.max_threshold_signal;

//     above_min_threshold & below_max_threshold
// }

// #[no_mangle]
// pub extern "C" fn process_sample_chunk(
//     filter_ptr: *mut c_void,
//     data: *mut f64,
//     length: usize,
// ) -> bool {
//     if filter_ptr.is_null() {
//         return false;
//     }
//     let state = unsafe { &mut *(filter_ptr as *mut Filter) };
//     let data_slice = unsafe { std::slice::from_raw_parts(data, length) };

//     let mut threshold_exceeded = false;
//     for &sample in data_slice {
//         state.process_sample(sample);
//         // let z_score = state.calculate_z_score();

//         let above_min_threshold = state.filtered_sample > state.min_threshold_signal;
//         let below_max_threshold = state.filtered_sample < state.max_threshold_signal;

//         if above_min_threshold & below_max_threshold {
//             threshold_exceeded = true;
//             break;
//         }
//     }

//     threshold_exceeded
// }
