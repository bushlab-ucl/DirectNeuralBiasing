use super::detectors::threshold::{ThresholdDetector, ThresholdDetectorConfig};
use super::filters::bandpass::{BandPassFilter, BandPassFilterConfig};
use super::signal_processor::{SignalProcessor, SignalProcessorConfig};
use super::triggers::pulse::{PulseTrigger, PulseTriggerConfig};

use std::collections::HashMap;
use std::time::Duration;

use pyo3::prelude::*;

#[pyclass]
pub struct PySignalProcessor {
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
pub fn direct_neural_biasing(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySignalProcessor>()?;
    Ok(())
}
