use super::super::filters::FilterInstance;
use super::{DetectionResult, DetectorInstance, RingBuffer};

#[derive(Clone)]
pub struct ThresholdDetectorConfig {
    pub filter_id: String,
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
    fn filter_id(&self) -> String {
        self.filter_id().clone()
    }

    fn process_sample(
        &mut self,
        _filters: &std::collections::HashMap<String, Box<dyn FilterInstance>>,
        // _sample: f64,
        _index: usize,
        z_score: f64,
    ) -> Option<DetectionResult> {
        self.buffer.add(z_score);

        // Count the number of z_scores in the buffer that exceed the threshold
        let above_threshold_count = self
            .buffer
            .buffer
            .iter()
            .filter(|&&z| z > self.config.threshold)
            .count();

        // Calculate the required count based on the sensitivity ratio and buffer capacity
        let required_count =
            (self.buffer.buffer.len() as f64 * self.config.sensitivity).ceil() as usize;

        // If the count of values above the threshold meets or exceeds the required count, trigger detection
        if above_threshold_count >= required_count {
            let confidence =
                (above_threshold_count as f64 / self.buffer.buffer.len() as f64) * 100.0;
            Some(DetectionResult {
                name: self.filter_id().clone(),
                confidence,
            })
        } else {
            None
        }
    }
}
