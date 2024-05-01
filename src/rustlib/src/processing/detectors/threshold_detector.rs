use std::collections::HashMap;

use pyo3::buffer;

use super::{DetectorInstance, RingBuffer};

#[derive(Clone)]
pub struct ThresholdDetectorConfig {
    pub filter_id: String, // ID of the filter whose output this detector should analyze
    pub threshold: f64,
    pub buffer_size: usize,
    pub sensitivity: f64,
}

#[derive(Clone)]
pub struct ThresholdDetector {
    config: ThresholdDetectorConfig,
    buffer: RingBuffer,
}

impl ThresholdDetector {
    pub fn new(config: ThresholdDetectorConfig) -> Self {
        if config.sensitivity < 0.0 || config.sensitivity > 1.0 {
            panic!("Sensitivity must be between 0 and 1.");
        }
        let buffer_size = config.buffer_size;
        Self {
            config,
            buffer: RingBuffer::new(buffer_size),
        }
    }
}

impl DetectorInstance for ThresholdDetector {
    fn process_sample(
        &mut self,
        results: &mut HashMap<String, f64>,
        index: usize,
        detector_id: &str,
    ) {
        // Fetch the filtered sample from results using the filter_id
        if let Some(&filtered_sample) =
            results.get(&format!("filters:{}:output", self.config.filter_id))
        {
            self.buffer.add(filtered_sample);

            // Count the number of values in the buffer that exceed the threshold
            let above_threshold_count = self
                .buffer
                .buffer
                .iter()
                .filter(|&&value| value > self.config.threshold)
                .count();

            let required_count =
                (self.buffer.buffer.len() as f64 * self.config.sensitivity).ceil() as usize;
            let detection_status = if above_threshold_count >= required_count {
                1.0
            } else {
                0.0
            };
            let confidence =
                (above_threshold_count as f64 / self.buffer.buffer.len() as f64) * 100.0;

            // Write detection status and confidence to the results
            results.insert(
                format!("detectors:{}:detected", detector_id),
                detection_status,
            );
            results.insert(format!("detectors:{}:confidence", detector_id), confidence);
        }
    }
}
