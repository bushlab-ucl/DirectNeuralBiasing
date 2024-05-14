use std::collections::HashMap;

use super::DetectorInstance;

#[derive(Clone)]
pub struct SlowWaveDetectorConfig {
    pub filter_id: String,
    pub threshold_sinusoid: f64,
    pub absolute_min_threshold: f64,
    pub absolute_max_threshold: f64,
}

#[derive(Clone)]
pub struct SlowWaveDetector {
    config: SlowWaveDetectorConfig,
    ongoing_wave: Vec<f64>,
    ongoing_wave_idx: Vec<usize>,
    last_sample: f64, // To keep track of the last sample for zero-crossing detection
}

impl SlowWaveDetector {
    pub fn new(config: SlowWaveDetectorConfig) -> Self {
        SlowWaveDetector {
            config,
            ongoing_wave: Vec::new(),
            ongoing_wave_idx: Vec::new(),
            last_sample: 0.0,
        }
    }
}

impl DetectorInstance for SlowWaveDetector {
    fn process_sample(
        &mut self,
        results: &mut HashMap<String, f64>,
        index: usize,
        detector_id: &str,
    ) {
        let filtered_sample = results
            .get(&format!(
                "filters:{}:filtered_sample",
                self.config.filter_id
            ))
            .cloned()
            .unwrap_or(0.0);

        // Detect zero-crossing from negative to positive
        if filtered_sample > 0.0 && self.last_sample <= 0.0 {
            // Analyze the ongoing wave data if it is not empty
            if !self.ongoing_wave.is_empty() {
                let detection = self.analyse_wave(results, detector_id);
                if detection {
                    // Output the detection status and increment the detected count
                    results.insert(format!("detectors:{}:detected", detector_id), 1.0);

                    // Construct a string of the detected wave indexes
                    let indexes_str = self
                        .ongoing_wave_idx
                        .iter()
                        .map(|&idx| idx.to_string())
                        .collect::<Vec<String>>()
                        .join(", ");

                    // Predict the next wave maxima
                    let half_period = (self.ongoing_wave_idx.len() / 2) as usize;
                    let next_maxima_idx = index + half_period;

                    // Output the detected wave indexes and the predicted next maxima
                    results.insert(
                        format!(
                            "detectors:{}:slow_wave_idx:{}:next_maxima",
                            detector_id, indexes_str
                        ),
                        next_maxima_idx as f64,
                    );
                }
                // Clear the ongoing wave data after analysis
                self.ongoing_wave.clear();
                self.ongoing_wave_idx.clear();
            }
        } else if filtered_sample < 0.0 {
            // Store the ongoing wave data for analysis
            self.ongoing_wave.push(filtered_sample);
            self.ongoing_wave_idx.push(index);
        }

        // If no detection, output the detection and confidence status as zero
        results
            .entry(format!("detectors:{}:detected", detector_id))
            .or_insert(0.0);
        results
            .entry(format!("detectors:{}:confidence", detector_id))
            .or_insert(0.0);

        // Update the last sample for zero-crossing detection
        self.last_sample = filtered_sample;
    }
}

impl SlowWaveDetector {
    /// Analyzes the collected wave data to determine if it meets the criteria for a slow wave.
    fn analyse_wave(&mut self, results: &mut HashMap<String, f64>, detector_id: &str) -> bool {
        let wave_length = self.ongoing_wave.len();

        // Ensure there is enough data to analyze
        if wave_length == 0 {
            return false;
        }

        // Find the minimum amplitude within the wave to define the peak
        let minima_idx = self.find_wave_minima();
        let peak_amplitude = self.ongoing_wave[minima_idx].abs();

        // Check if the amplitude is within the specified thresholds
        if peak_amplitude > self.config.absolute_min_threshold
            && peak_amplitude < self.config.absolute_max_threshold
        {
            let sinusoid = self.construct_cosine_wave(minima_idx, wave_length);
            let correlation = self.calculate_correlation(&sinusoid);

            // Check if the correlation with a sinusoidal wave exceeds the threshold
            if correlation > self.config.threshold_sinusoid {
                results.insert(format!("detectors:{}:confidence", detector_id), correlation);
                return true;
            }

            // If the correlation is below the threshold, output the confidence value
            results.insert(format!("detectors:{}:confidence", detector_id), correlation);
            return false;
        }

        // If the amplitude is outside the specified thresholds, output a confidence of 0
        results.insert(format!("detectors:{}:confidence", detector_id), 0.0);
        return false;
    }

    /// Finds the index of the minimum value within the ongoing_wave vector, which represents the peak of the wave.
    fn find_wave_minima(&self) -> usize {
        self.ongoing_wave
            .iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap())
            .map(|(idx, _)| idx)
            .unwrap_or(0)
    }

    /// Constructs a cosine wave that matches the frequency and amplitude of the detected wave.
    fn construct_cosine_wave(&self, peak_idx: usize, wave_length: usize) -> Vec<f64> {
        let frequency = 1.0 / (wave_length as f64 / 2.0); // Calculate the frequency based on the wave length
        let amplitude = self.ongoing_wave[peak_idx]; // Use the amplitude at the peak index
        (0..wave_length)
            .map(|i| amplitude * (i as f64 * 2.0 * std::f64::consts::PI * frequency).cos())
            .collect()
    }

    /// Calculates the correlation between the ongoing_wave and a generated sinusoid to check for pattern match.
    fn calculate_correlation(&self, sinusoid: &Vec<f64>) -> f64 {
        let mean_wave = self.ongoing_wave.iter().sum::<f64>() / self.ongoing_wave.len() as f64;
        let mean_sinusoid = sinusoid.iter().sum::<f64>() / sinusoid.len() as f64;

        let covariance: f64 = self
            .ongoing_wave
            .iter()
            .zip(sinusoid.iter())
            .map(|(&x, &y)| (x - mean_wave) * (y - mean_sinusoid))
            .sum();
        let std_dev_wave = (self
            .ongoing_wave
            .iter()
            .map(|&x| (x - mean_wave).powi(2))
            .sum::<f64>()
            / self.ongoing_wave.len() as f64)
            .sqrt();
        let std_dev_sinusoid = (sinusoid
            .iter()
            .map(|&x| (x - mean_sinusoid).powi(2))
            .sum::<f64>()
            / sinusoid.len() as f64)
            .sqrt();

        covariance / (std_dev_wave * std_dev_sinusoid)
    }
}
