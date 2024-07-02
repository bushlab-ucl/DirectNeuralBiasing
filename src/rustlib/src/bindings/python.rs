use crate::processing::detectors::slow_wave::{SlowWaveDetector, SlowWaveDetectorConfig};
use crate::processing::detectors::threshold::{ThresholdDetector, ThresholdDetectorConfig};
use crate::processing::filters::bandpass::{BandPassFilter, BandPassFilterConfig};
use crate::processing::signal_processor::{SignalProcessor, SignalProcessorConfig};
use crate::processing::triggers::pulse::{PulseTrigger, PulseTriggerConfig};

use std::collections::HashMap;

use pyo3::prelude::*;

#[pyclass]
pub struct PySignalProcessor {
    processor: SignalProcessor,
}

#[pymethods]
impl PySignalProcessor {
    #[new]
    pub fn new(verbose: bool, fs: f64) -> Self {
        let config = SignalProcessorConfig { verbose, fs };
        PySignalProcessor {
            processor: SignalProcessor::new(config),
        }
    }

    pub fn add_filter(&mut self, id: String, f_low: f64, f_high: f64, fs: f64) {
        let config = BandPassFilterConfig {
            id,
            f_low,
            f_high,
            fs,
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
        z_score_threshold: f64,
        sinusoidness_threshold: f64,
    ) {
        let config = SlowWaveDetectorConfig {
            id,
            filter_id,
            z_score_threshold,
            sinusoidness_threshold,
        };
        let detector = SlowWaveDetector::new(config);
        self.processor.add_detector(Box::new(detector));
    }

    pub fn add_pulse_trigger(
        &mut self,
        id: String,
        activation_detector_id: String,
        inhibition_detector_id: String,
        inhibition_cooldown_ms: f64,
        pulse_cooldown_ms: f64,
    ) {
        let config = PulseTriggerConfig {
            id,
            activation_detector_id,
            inhibition_detector_id,
            inhibition_cooldown_ms,
            pulse_cooldown_ms,
        };
        let trigger = PulseTrigger::new(config);
        self.processor.add_trigger(Box::new(trigger));
    }

    // pub fn run(&mut self, data: Vec<f64>) -> Vec<HashMap<String, f64>> {
    //     self.processor.index = 0; // reset the index
    //     self.processor.run(data)
    // }

    pub fn reset_index(&mut self) {
        self.processor.index = 0; // reset the index
    }

    pub fn run_chunk(&mut self, data: Vec<f64>) -> Vec<HashMap<String, f64>> {
        self.processor.run_chunk(data)
    }
}

/// A Python module implemented in Rust.
#[pymodule]
pub fn direct_neural_biasing(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PySignalProcessor>()?;
    Ok(())
}
