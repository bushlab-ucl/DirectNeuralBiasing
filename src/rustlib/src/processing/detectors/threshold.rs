use std::collections::HashMap;

use super::{DetectorInstance, RingBuffer, Statistics};

#[derive(Clone)]
pub struct ThresholdDetectorConfig {
    pub id: String,
    pub filter_id: String,
    pub z_score_threshold: f64,
    pub buffer_size: usize,
    pub sensitivity: f64,
}

#[derive(Clone)]
pub struct ThresholdDetector {
    config: ThresholdDetectorConfig,
    buffer: RingBuffer,
    statistics: Statistics,
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
            statistics: Statistics::new(),
        }
    }
}

impl DetectorInstance for ThresholdDetector {
    fn id(&self) -> &str {
        &self.config.id
    }

    fn process_sample(
        &mut self,
        results: &mut HashMap<String, f64>,
        _index: usize,
        detector_id: &str,
    ) {
        // Construct the key to fetch the filtered sample
        let filter_key = format!("filters:{}:filtered_sample", self.config.filter_id);

        // Fetch the filtered sample using a cloned unwrap_or to handle the absence gracefully
        let filtered_sample = results.get(&filter_key).cloned().unwrap_or(0.0);

        // Update statistics with the new filtered sample
        self.statistics.update_statistics(filtered_sample);

        // Add the z-score to the buffer
        self.buffer.add(self.statistics.z_score);

        // Calculate the number of values in the buffer that exceed the threshold
        let above_threshold_count = self
            .buffer
            .buffer
            .iter()
            .filter(|&&value| value > self.config.z_score_threshold)
            .count();

        // Calculate confidence as a percentage of samples above the threshold regardless of detection status
        let confidence = if self.buffer.buffer.len() > 0 {
            (above_threshold_count as f64 / self.buffer.buffer.len() as f64) * 100.0
        } else {
            0.0 // Prevent division by zero if buffer is empty
        };

        // Determine the detection status based on the count and sensitivity
        let detection_status = if (above_threshold_count as f64 / self.buffer.buffer.len() as f64)
            > self.config.sensitivity
        {
            1.0
        } else {
            0.0
        };

        // Update the results HashMap with detection status and confidence
        results.insert(
            format!("detectors:{}:detected", detector_id),
            detection_status,
        );
        results.insert(format!("detectors:{}:confidence", detector_id), confidence);
    }
}
