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
        let filter_config = BandPassFilterConfig { f0, fs };
        let filter = BandPassFilter::new(filter_config);
        self.processor.add_filter(id, Box::new(filter));
    }

    pub fn add_threshold_detector(
        &mut self,
        id: String,
        filter_id: String,
        threshold: f64,
        buffer_size: usize,
        sensitivity: f64,
    ) {
        let detector_id = id.clone();
        let config = ThresholdDetectorConfig {
            filter_id,
            threshold,
            buffer_size,
            sensitivity,
        };
        let detector = ThresholdDetector::new(config);
        self.processor.add_detector(detector_id, Box::new(detector));
    }

    pub fn add_pulse_trigger(
        &mut self,
        id: String,
        activation_detector_id: String,
        inhibition_detector_id: String,
        activate_cooldown: usize,
        inhibit_cooldown: usize,
    ) {
        let trigger_id = id.clone();
        let config = PulseTriggerConfig {
            trigger_id: id,
            activation_detector_id,
            inhibition_detector_id,
            activate_cooldown: Duration::from_secs(activate_cooldown as u64),
            inhibit_cooldown: Duration::from_secs(inhibit_cooldown as u64),
        };
        let trigger = PulseTrigger::new(config);
        self.processor.add_trigger(trigger_id, Box::new(trigger));
    }

    pub fn run(&mut self, data: Vec<f64>) -> Vec<HashMap<String, f64>> {
        self.processor.run(data)
    }
}

/// A Python module implemented in Rust.
#[pymodule]
fn direct_neural_biasing(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    m.add_class::<PySignalProcessor>()?;

    Ok(())
}

// // -----------------------------------------------------------------------------
// // PY03 PYTHON LOGIC
// // -----------------------------------------------------------------------------

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
