use super::{DetectionResult, DetectorInstance, RingBuffer};

pub struct ThresholdDetector {
    name: String,
    buffer: RingBuffer,
    z_score_threshold: f64,
    sensitivity: usize, // Ratio of buffer values above the threshold to trigger detection
}

impl ThresholdDetector {
    pub fn new(
        name: String,
        buffer_capacity: usize,
        z_score_threshold: f64,
        sensitivity: usize,
    ) -> Self {
        Self {
            name,
            buffer: RingBuffer::new(buffer_capacity),
            z_score_threshold,
            sensitivity,
        }
    }
}

impl DetectorInstance for ThresholdDetector {
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

        // Calculate the confidence ratio based on the count and buffer length
        let buffer_length = self.buffer.buffer.len();
        if above_threshold_count >= self.sensitivity {
            let confidence_ratio = (above_threshold_count as f64 / buffer_length as f64) * 100.0;
            Some(DetectionResult {
                name: self.name.clone(),
                confidence_ratio,
            })
        } else {
            None
        }
    }
}
