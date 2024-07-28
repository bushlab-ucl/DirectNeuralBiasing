use super::{DetectorInstance, RingBuffer, Statistics};
use crate::processing::signal_processor::SignalProcessorConfig;
use std::collections::HashMap;

pub struct ThresholdDetectorConfig {
    pub id: String,
    pub filter_id: String,
    pub z_score_threshold: f64,
    pub buffer_size: usize,
    pub sensitivity: f64,
}

pub struct Keys {
    filter_key: &'static str,
    detected: &'static str,
    confidence: &'static str,
    statistics_sum: &'static str,
    statistics_sum_of_squares: &'static str,
    statistics_count: &'static str,
    statistics_mean: &'static str,
    statistics_z_score: &'static str,
    statistics_std_dev: &'static str,
}

pub struct ThresholdDetector {
    config: ThresholdDetectorConfig,
    buffer: RingBuffer,
    statistics: Statistics,
    keys: Keys,
}

impl ThresholdDetector {
    pub fn new(config: ThresholdDetectorConfig) -> Self {
        if config.sensitivity < 0.0 || config.sensitivity > 1.0 {
            panic!("Sensitivity must be between 0 and 1.");
        }
        let buffer_size = config.buffer_size;
        let keys = Keys {
            filter_key: Box::leak(
                format!("filters:{}:filtered_sample", config.filter_id).into_boxed_str(),
            ),
            detected: Box::leak(format!("detectors:{}:detected", config.id).into_boxed_str()),
            confidence: Box::leak(format!("detectors:{}:confidence", config.id).into_boxed_str()),
            statistics_sum: Box::leak(
                format!("detectors:{}:statistics:sum", config.id).into_boxed_str(),
            ),
            statistics_sum_of_squares: Box::leak(
                format!("detectors:{}:statistics:sum_of_squares", config.id).into_boxed_str(),
            ),
            statistics_count: Box::leak(
                format!("detectors:{}:statistics:count", config.id).into_boxed_str(),
            ),
            statistics_mean: Box::leak(
                format!("detectors:{}:statistics:mean", config.id).into_boxed_str(),
            ),
            statistics_z_score: Box::leak(
                format!("detectors:{}:statistics:z_score", config.id).into_boxed_str(),
            ),
            statistics_std_dev: Box::leak(
                format!("detectors:{}:statistics:std_dev", config.id).into_boxed_str(),
            ),
        };
        Self {
            config,
            buffer: RingBuffer::new(buffer_size),
            statistics: Statistics::new(),
            keys,
        }
    }
}

impl DetectorInstance for ThresholdDetector {
    fn id(&self) -> &str {
        &self.config.id
    }

    fn filter_id(&self) -> String {
        self.config.filter_id.clone()
    }

    fn process_sample(
        &mut self,
        global_config: &SignalProcessorConfig,
        results: &mut HashMap<&'static str, f64>,
        _index: usize,
    ) {
        // Fetch the filtered sample using a cloned unwrap_or to handle the absence gracefully
        let filtered_sample = results.get(&self.keys.filter_key as &str).cloned().unwrap();

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
            above_threshold_count as f64 / self.buffer.buffer.len() as f64
        } else {
            0.0 // Prevent division by zero if buffer is empty
        };

        // Determine the detection status based on the count and sensitivity
        let detection_status = if confidence > self.config.sensitivity {
            1.0
        } else {
            0.0
        };

        // Update the results HashMap with detection status and confidence
        results.insert(self.keys.detected, detection_status);
        results.insert(self.keys.confidence, confidence);

        // If verbose, add more items to the results HashMap
        if global_config.verbose {
            results.insert(self.keys.statistics_sum, self.statistics.sum);
            results.insert(
                self.keys.statistics_sum_of_squares,
                self.statistics.sum_of_squares,
            );
            results.insert(self.keys.statistics_count, self.statistics.count as f64);
            results.insert(self.keys.statistics_mean, self.statistics.mean);
            results.insert(self.keys.statistics_z_score, self.statistics.z_score);
            results.insert(self.keys.statistics_std_dev, self.statistics.std_dev);
        }
    }
}
