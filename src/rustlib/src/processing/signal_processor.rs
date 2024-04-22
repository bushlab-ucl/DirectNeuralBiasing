use super::detectors::{DetectionResult, DetectorInstance};
use crate::filters::bandpass::BandPassFilter;
use crate::utils::log::log_to_file;
// use rayon::prelude::*;
use std::time::Instant;

// use pyo3::prelude::*;
// use std::os::raw::c_void;

// use super::detectors::slow_wave::SlowWaveDetector;

// -----------------------------------------------------------------------------
// RUST CORE LOGIC
// -----------------------------------------------------------------------------

// SIGNAL PROCESSOR COMPONENT ----------------------------------------------------------

pub struct SignalProcessor {
    pub index: usize,
    filter: Filter,
    statistics: Statistics,
    detectors: Detectors,
    config: Config,
}

impl SignalProcessor {
    pub fn new(filter_instance: BandPassFilter, config: Config) -> Self {
        SignalProcessor {
            index: 0,
            filter: Filter::new(filter_instance),
            statistics: Statistics::new(),
            detectors: Detectors::new(),
            config,
        }
    }

    pub fn add_detector(&mut self, detector: Box<dyn DetectorInstance>) {
        self.detectors.add_detector(detector);
    }

    pub fn process_sample(&mut self, sample: f64) -> Vec<DetectionResult> {
        let start = Instant::now(); // Start timing

        self.filter.filter_sample(sample);
        let filtered_sample = self.filter.filtered_sample;
        self.statistics.update_statistics(filtered_sample);

        let detection_results =
            self.detectors
                .run_detectors(filtered_sample, self.index, self.statistics.z_score);

        if self.config.logging {
            let formatted_message = format!(
                "index: {}, sample: {}, filtered_sample: {}, z_score: {}",
                self.index, sample, filtered_sample, self.statistics.z_score
            );
            log_to_file(&formatted_message).expect("Failed to write to log file");

            for detection in &detection_results {
                let log_message = format!(
                    "{} detected - confidence: {}",
                    detection.name, detection.confidence
                );
                log_to_file(&log_message).expect("Failed to write detection to log file");
            }
        }

        let duration = start.elapsed(); // Calculate how long the function took
        println!("process_sample took: {:?}", duration);

        self.index += 1;
        detection_results
    }
}

// -----------------------------------------------------------------------------
// SIGNAL PROCESSOR SUBCOMPONENTS
// -----------------------------------------------------------------------------

// CONFIG COMPONENT ------------------------------------------------------------

pub struct Config {
    logging: bool,
}

impl Config {
    pub fn new(logging: bool) -> Self {
        Self { logging }
    }
}

// FILTER COMPONENT ------------------------------------------------------------

struct Filter {
    filter: BandPassFilter,
    filtered_sample: f64,
}

impl Filter {
    fn new(filter: BandPassFilter) -> Self {
        Self {
            filter,
            filtered_sample: 0.0,
        }
    }

    fn filter_sample(&mut self, sample: f64) {
        self.filtered_sample = self.filter.filter_sample(sample); // Placeholder for actual filter implementation
    }
}

// STATISTICS COMPONENT --------------------------------------------------------

struct Statistics {
    sum: f64,
    count: usize,
    mean: f64,
    std_dev: f64,
    z_score: f64,
}

impl Statistics {
    fn new() -> Self {
        Self {
            sum: 0.0,
            count: 0,
            mean: 0.0,
            std_dev: 0.0,
            z_score: 0.0,
        }
    }

    fn update_statistics(&mut self, sample: f64) {
        self.sum += sample;
        self.count += 1;
        self.mean = self.sum / self.count as f64;
        // Update standard deviation calculation to correctly reflect population/std sample deviation as needed
        self.std_dev = ((self.sum / self.count as f64) - self.mean.powi(2)).sqrt();
        self.z_score = (sample - self.mean) / self.std_dev;
    }
}

// DETECTOR COMPONENT ----------------------------------------------------------

pub struct Detectors {
    detectors: Vec<Box<dyn DetectorInstance>>, // Ensure thread safety
}

impl Detectors {
    pub fn new() -> Self {
        Self {
            detectors: Vec::new(),
        }
    }

    pub fn add_detector(&mut self, detector: Box<dyn DetectorInstance>) {
        self.detectors.push(detector);
    }

    pub fn run_detectors(
        &mut self,
        sample: f64,
        index: usize,
        z_score: f64,
    ) -> Vec<DetectionResult> {
        self.detectors
            .iter_mut()
            .filter_map(|detector| detector.process_sample(sample, index, z_score))
            .collect()
    }
}

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
