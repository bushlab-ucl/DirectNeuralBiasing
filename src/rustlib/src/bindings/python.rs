use crate::processing::detectors::slow_wave::{SlowWaveDetector, SlowWaveDetectorConfig};
use crate::processing::detectors::threshold::{ThresholdDetector, ThresholdDetectorConfig};
use crate::processing::filters::bandpass::{BandPassFilter, BandPassFilterConfig};
use crate::processing::signal_processor::{SignalProcessor, SignalProcessorConfig};
use crate::processing::triggers::pulse::{PulseTrigger, PulseTriggerConfig};

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
    pub fn new(verbose: bool, downsample_rate: usize) -> Self {
        let config = SignalProcessorConfig {
            verbose,
            downsample_rate,
        };
        PySignalProcessor {
            processor: SignalProcessor::new(config),
        }
    }

    pub fn add_filter(&mut self, id: String, f0: f64, fs: f64, downsample_rate: usize) {
        let config = BandPassFilterConfig {
            id,
            f0,
            fs,
            downsample_rate,
        };
        let filter = BandPassFilter::new(config);
        self.processor.add_filter(Box::new(filter));
    }

    pub fn add_threshold_detector(
        &mut self,
        id: String,
        filter_id: String,
        z_score_threshold: f64,
        buffer_size: usize,
        sensitivity: f64,
    ) {
        let config = ThresholdDetectorConfig {
            id,
            filter_id,
            z_score_threshold,
            buffer_size,
            sensitivity,
        };
        let detector = ThresholdDetector::new(config);
        self.processor.add_detector(Box::new(detector));
    }

    pub fn add_slow_wave_detector(
        &mut self,
        id: String,
        filter_id: String,
        sinusoid_threshold: f64,
        absolute_min_threshold: f64,
        absolute_max_threshold: f64,
    ) {
        let config = SlowWaveDetectorConfig {
            id,
            filter_id,
            sinusoid_threshold,
            absolute_min_threshold,
            absolute_max_threshold,
        };
        let detector = SlowWaveDetector::new(config);
        self.processor.add_detector(Box::new(detector));
    }

    pub fn add_pulse_trigger(
        &mut self,
        id: String,
        activation_detector_id: String,
        inhibition_detector_id: String,
        activation_cooldown_ms: f64,
        inhibition_cooldown_ms: f64,
    ) {
        let config = PulseTriggerConfig {
            id,
            activation_detector_id,
            inhibition_detector_id,
            activation_cooldown: Duration::from_millis(activation_cooldown_ms as u64),
            inhibition_cooldown: Duration::from_millis(inhibition_cooldown_ms as u64),
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
