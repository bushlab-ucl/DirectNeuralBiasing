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
        sample: f64,
        _index: usize,
        mean: f64,
        std_dev: f64,
    ) -> Option<DetectionResult> {
        self.buffer.add(sample);
        let z_scores: Vec<f64> = self
            .buffer
            .buffer
            .iter()
            .map(|&s| {
                if std_dev != 0.0 {
                    (s - mean) / std_dev
                } else {
                    0.0
                }
            })
            .collect();

        let above_threshold_count = z_scores
            .iter()
            .filter(|&&z| z > self.z_score_threshold)
            .count();
        let buffer_length = z_scores.len();

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
