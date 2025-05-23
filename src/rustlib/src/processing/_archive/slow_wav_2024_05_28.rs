use super::DetectorInstance;
use crate::processing::signal_processor::SignalProcessorConfig;

use std::collections::HashMap;

#[derive(Clone)]
pub struct SlowWaveDetectorConfig {
    pub id: String,
    pub filter_id: String,
    pub sinusoid_threshold: f64,
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
    fn id(&self) -> &str {
        &self.config.id
    }

    fn filter_id(&self) -> String {
        self.config.filter_id.clone()
    }

    fn process_sample(
        &mut self,
        global_config: &SignalProcessorConfig,
        results: &mut HashMap<String, f64>,
        index: usize,
    ) {
        let filtered_sample = results
            .get(&format!(
                "filters:{}:filtered_sample",
                self.config.filter_id
            ))
            .cloned()
            .unwrap_or(0.0);

        // Detect zero-crossing from positive to negative
        if filtered_sample < 0.0 && self.last_sample >= 0.0 {
            // Analyze the ongoing wave data if it is not empty
            if !self.ongoing_wave.is_empty() {
                let detection = self.analyse_wave(results);
                if detection {
                    // Output the detection status and increment the detected count
                    results.insert(format!("detectors:{}:detected", self.config.id), 1.0);

                    // Construct a string of the detected wave indexes
                    let indexes_str = self
                        .ongoing_wave_idx
                        .iter()
                        .map(|&idx| idx.to_string())
                        .collect::<Vec<String>>()
                        .join(", ");

                    // Predict the next wave maxima
                    let half_period = self.ongoing_wave_idx.len() / 2;
                    let next_maxima_idx = index + half_period;

                    // Output the detected wave indexes and the predicted next maxima
                    results.insert(
                        format!(
                            "detectors:{}:slow_wave_idx:{}:next_maxima",
                            self.config.id, indexes_str
                        ),
                        next_maxima_idx as f64,
                    );
                }
                // Clear the ongoing wave data after analysis
                self.ongoing_wave.clear();
                self.ongoing_wave_idx.clear();
            }
        } else {
            // Store the ongoing wave data for analysis
            self.ongoing_wave.push(filtered_sample);
            self.ongoing_wave_idx.push(index);
        }

        // If no detection, output the detection and confidence status as zero
        results
            .entry(format!("detectors:{}:detected", self.config.id))
            .or_insert(0.0);
        results
            .entry(format!("detectors:{}:confidence", self.config.id))
            .or_insert(0.0);

        // Update the last sample for zero-crossing detection
        self.last_sample = filtered_sample;
    }
}

impl SlowWaveDetector {
    /// Analyzes the collected wave data to determine if it meets the criteria for a slow wave.
    fn analyse_wave(&mut self, results: &mut HashMap<String, f64>) -> bool {
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
            if correlation > self.config.sinusoid_threshold {
                results.insert(
                    format!("detectors:{}:confidence", self.config.id),
                    correlation,
                );
                return true;
            }

            // If the correlation is below the threshold, output the confidence value
            results.insert(
                format!("detectors:{}:confidence", self.config.id),
                correlation,
            );
            return false;
        }

        // If the amplitude is outside the specified thresholds, output a confidence of 0
        results.insert(format!("detectors:{}:confidence", self.config.id), 0.0);
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
