use super::{DetectionResult, DetectorInstance, RingBuffer};

#[derive(Clone)]
pub struct ThresholdDetector {
    name: String,
    buffer: RingBuffer,
    z_score_threshold: f64,
    sensitivity: f64,
}

impl ThresholdDetector {
    pub fn new(
        name: String,
        z_score_threshold: f64, // Threshold for z_score to trigger detection
        buffer_capacity: usize, // Number of z_scores to store in buffer
        sensitivity: f64, // Sensitivity as a ratio between 0 and 1 - Ratio of buffer values above the threshold to trigger detection
    ) -> Self {
        if sensitivity < 0.0 || sensitivity > 1.0 {
            panic!("Sensitivity must be between 0 and 1.");
        }
        Self {
            name,
            z_score_threshold,
            buffer: RingBuffer::new(buffer_capacity),
            sensitivity,
        }
    }
}

impl DetectorInstance for ThresholdDetector {
    fn name(&self) -> String {
        self.name.clone()
    }

    fn process_sample(
        &mut self,
        _sample: f64,
        _index: usize,
        z_score: f64,
    ) -> Option<DetectionResult> {
        self.buffer.add(z_score);

        // Count the number of z_scores in the buffer that exceed the threshold
        let above_threshold_count = self
            .buffer
            .buffer
            .iter()
            .filter(|&&z| z > self.z_score_threshold)
            .count();

        // Calculate the required count based on the sensitivity ratio and buffer capacity
        let required_count = (self.buffer.buffer.len() as f64 * self.sensitivity).ceil() as usize;

        // If the count of values above the threshold meets or exceeds the required count, trigger detection
        if above_threshold_count >= required_count {
            let confidence =
                (above_threshold_count as f64 / self.buffer.buffer.len() as f64) * 100.0;
            Some(DetectionResult {
                name: self.name.clone(),
                confidence,
            })
        } else {
            None
        }
    }
}
