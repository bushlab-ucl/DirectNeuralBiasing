use super::detectors::DetectorInstance;
use super::filters::FilterInstance;
use super::triggers::TriggerInstance;
// use crate::utils::log::log_to_file;
// use rayon::prelude::*;
use std::collections::HashMap;

// use pyo3::prelude::*;
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

    pub fn add_filter(&mut self, id: String, filter: Box<dyn FilterInstance>) {
        self.filters.insert(id, filter);
    }

    pub fn add_detector(&mut self, id: String, detector: Box<dyn DetectorInstance>) {
        self.detectors.insert(id, detector);
    }

    pub fn add_trigger(&mut self, id: String, trigger: Box<dyn TriggerInstance>) {
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

// // Define PyThresholdDetector without `Box`
// #[pyclass]
// struct PyThresholdDetector {
//     detector: ThresholdDetector,
// }

// #[pymethods]
// impl PyThresholdDetector {
//     #[new]
//     fn new(name: String, z_score_threshold: f64, buffer_capacity: usize, sensitivity: f64) -> Self {
//         PyThresholdDetector {
//             detector: ThresholdDetector::new(name, z_score_threshold, buffer_capacity, sensitivity),
//         }
//     }
// }

// // PyControllerConfig without `std::time::Duration`
// #[pyclass]
// struct PyConfig {
//     config: Config,
// }

// #[pymethods]
// impl PyConfig {
//     #[new]
//     fn new(
//         downsampling_rate: usize,
//         trigger_cooldown: usize,
//         detector_cooldown: usize,
//         logging: bool,
//     ) -> Self {
//         let config = Config {
//             downsampling_rate,
//             trigger_cooldown: std::time::Duration::from_secs(trigger_cooldown as u64),
//             detector_cooldown: std::time::Duration::from_secs(detector_cooldown as u64),
//             logging,
//         };
//         PyConfig { config }
//     }
// }

// // Define PyController without `Box<dyn DetectorInstance>`
// #[pyclass]
// struct PyController {
//     controller: Controller,
// }

// #[pymethods]
// impl PyController {
//     #[new]
//     fn new(
//         downsampling_rate: usize,
//         trigger_cooldown: std::time::Duration,
//         detector_cooldown: std::time::Duration,
//         logging: bool,
//     ) -> Self {
//         let config = Config {
//             downsampling_rate,
//             trigger_cooldown,
//             detector_cooldown,
//             logging,
//         };
//         PyController {
//             controller: Controller::new(config),
//         }
//     }

//     fn add_active_detector(&mut self, detector: &PyThresholdDetector) {
//         self.controller
//             .add_active_detector(Box::new(detector.detector.clone()));
//     }

//     fn add_cooldown_detector(&mut self, detector: &PyThresholdDetector) {
//         self.controller
//             .add_cooldown_detector(Box::new(detector.detector.clone()));
//     }
// }

// // Define PySignalProcessor without `Box<dyn DetectorInstance>`
// #[pyclass]
// struct PySignalProcessor {
//     processor: SignalProcessor,
// }

// #[pymethods]
// impl PySignalProcessor {
//     #[new]
//     fn new(f0: f64, fs: f64, py_controller: &PyController, config: &PyConfig) -> Self {
//         let bandpass = BandPassFilter::butterworth(f0, fs);
//         let processor = SignalProcessor::new(bandpass, py_controller.controller, config.config);
//         PySignalProcessor { processor }
//     }

//     fn process_sample(&mut self, sample: f64) -> Vec<(String, bool, f64)> {
//         let output = self.processor.process_sample(sample);
//         output
//             .detector_outputs
//             .iter()
//             .map(|det| (det.name.clone(), det.detected, det.confidence))
//             .collect()
//     }
// }

// #[pymodule]
// #[pyo3(name = "direct_neural_biasing")]
// fn direct_neural_biasing(m: &Bound<'_, PyModule>) -> PyResult<()> {
//     m.add_class::<PySignalProcessor>()?;
//     m.add_class::<PyThresholdDetector>()?;
//     m.add_class::<PyController>()?;
//     Ok(())
// }

// // -----------------------------------------------------------------------------
// // PY03 PYTHON LOGIC
// // -----------------------------------------------------------------------------

// #[pyclass]
// pub struct PyFilter {
//     state: Filter,
// }

// #[pymethods]
// impl PyFilter {
//     #[new]
//     pub fn new(
//         f0_l: f64,
//         f0_h: f64,
//         fs: f64,
//         min_threshold_signal: f64,
//         max_threshold_signal: f64,
//         refractory_period: usize,
//         delay_to_up_state: usize,
//         threshold_sinusoid: f64,
//         logging: bool,
//     ) -> Self {
//         let bounds: Vec<f64> = vec![f0_l, f0_h];
//         let filter = BandPassFilter::with_bounds(bounds, fs);
//         PyFilter {
//             state: Filter {
//                 filter,
//                 sum: 0.0,
//                 count: 0,
//                 min_threshold_signal,
//                 max_threshold_signal,
//                 mean: 0.0,
//                 sum_of_squares: 0.0,
//                 std_dev: 1.0,
//                 filtered_sample: 0.0,
//                 prev_sample: 0.0,
//                 samples_since_zero_crossing: 0,
//                 current_index: 0,
//                 ongoing_wave: Vec::new(),
//                 ongoing_wave_idx: Vec::new(),
//                 detected_waves_idx: Vec::new(),
//                 refractory_period,
//                 refractory_samples_to_skip: 0,
//                 delay_to_up_state,
//                 absolute_min_threshold: 0.0,
//                 absolute_max_threshold: 0.0,
//                 threshold_sinusoid,
//                 logging,
//             },
//         }
//     }

//     pub fn filter_signal(&mut self, data: Vec<f64>) -> PyResult<(Vec<f64>, Vec<Vec<usize>>)> {
//         let mut filtered_signal = Vec::with_capacity(data.len());
//         for (idx, &sample) in data.iter().enumerate() {
//             self.state.current_index = idx;
//             self.state.process_sample(sample);
//             filtered_signal.push(self.state.filtered_sample);
//         }
//         Ok((filtered_signal, self.state.detected_waves_idx.clone()))
//     }
// }

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
