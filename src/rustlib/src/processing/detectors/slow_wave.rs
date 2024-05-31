use super::{DetectorInstance, Statistics};
use crate::processing::signal_processor::SignalProcessorConfig;

use std::collections::HashMap;

#[derive(Clone)]
pub struct SlowWaveDetectorConfig {
    pub id: String,
    pub filter_id: String,
    pub z_score_threshold: f64,
    pub sinusoidness_threshold: f64,
}

#[derive(Clone)]
pub struct SlowWaveDetector {
    config: SlowWaveDetectorConfig,
    statistics: Statistics,
    last_sample: f64,
    is_downwave: bool,
    ongoing_wave_z_scores: Vec<f64>,
    downwave_start_index: Option<usize>,
    downwave_end_index: Option<usize>,
    predicted_next_maxima_index: Option<usize>,
}

impl SlowWaveDetector {
    pub fn new(config: SlowWaveDetectorConfig) -> Self {
        SlowWaveDetector {
            config,
            statistics: Statistics::new(),
            last_sample: 0.0,
            is_downwave: false,
            ongoing_wave_z_scores: Vec::new(),
            downwave_start_index: Some(0),
            downwave_end_index: Some(0),
            predicted_next_maxima_index: Some(0),
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
        // Construct the key to fetch the filtered sample
        let filter_key = format!("filters:{}:filtered_sample", self.config.filter_id);

        // Fetch the filtered sample using a cloned unwrap_or to handle the absence gracefully
        let filtered_sample = results.get(&filter_key).cloned().unwrap_or(0.0);

        // Update statistics with the new filtered sample
        self.statistics.update_statistics(filtered_sample);

        // Detect start of downwave (zero-crossing from positive to negative)
        if self.last_sample >= 0.0 && filtered_sample < 0.0 {
            self.is_downwave = true;
            self.downwave_start_index = Some(index);
        }

        // If downwave, store the ongoing wave z_score for analysis
        if self.is_downwave {
            self.ongoing_wave_z_scores.push(self.statistics.z_score);
        }

        // Detect end of ongoing downwave and analyse (zero-crossing from negative to positive)
        if self.is_downwave && self.last_sample <= 0.0 && filtered_sample > 0.0 {
            self.is_downwave = false;
            self.downwave_end_index = Some(index);

            // Analyze the wave
            let (detected, peak_z_score_amplitude, sinusoidness) =
                self.analyse_wave(global_config, results);

            // Predict next maxima and output to results
            if detected {
                // Predict the next wave maxima
                let half_period = self.ongoing_wave_z_scores.len() / 2;
                self.predicted_next_maxima_index = Some(index + half_period);

                // Output the detection status and wave index values
                results.insert(format!("detectors:{}:detected", self.config.id), 1.0);

                results.insert(
                    format!("detectors:{}:downwave_start_index", self.config.id),
                    self.downwave_start_index.unwrap() as f64,
                );

                results.insert(
                    format!("detectors:{}:downwave_end_index", self.config.id),
                    self.downwave_end_index.unwrap() as f64,
                );

                results.insert(
                    format!("detectors:{}:predicted_next_maxima_index", self.config.id),
                    self.predicted_next_maxima_index.unwrap() as f64,
                );
            } else {
                // Output the detection status as zero
                results.insert(format!("detectors:{}:detected", self.config.id), 0.0);
            }

            // Output the peak amplitude and sinusoidness values
            results.insert(
                format!("detectors:{}:peak_z_score_amplitude", self.config.id),
                peak_z_score_amplitude,
            );

            results.insert(
                format!("detectors:{}:sinusoidness", self.config.id),
                sinusoidness,
            );

            // Clear the ongoing wave data after analysis
            self.ongoing_wave_z_scores.clear();
            self.downwave_start_index = None;
            self.downwave_end_index = None;
        } else {
            // Output the detection status as zero
            results.insert(format!("detectors:{}:detected", self.config.id), 0.0);
        }

        // Update the last sample for zero-crossing detection
        self.last_sample = filtered_sample;
    }
}

impl SlowWaveDetector {
    /// Analyzes the collected wave data to determine if it meets the criteria for a slow wave.
    fn analyse_wave(
        &mut self,
        _global_config: &SignalProcessorConfig, // maybe remove
        _results: &mut HashMap<String, f64>,    // maybe remove
    ) -> (bool, f64, f64) {
        let wave_length = self.ongoing_wave_z_scores.len();

        // Find the minimum amplitude within the wave to define the peak
        let minima_idx = self.find_wave_minima();
        let peak_z_score_amplitude = self.ongoing_wave_z_scores[minima_idx].abs();

        // Check if the amplitude is above the threshold
        if peak_z_score_amplitude < self.config.z_score_threshold {
            return (false, peak_z_score_amplitude, -1.0); // -1 indicates no sinusoidal pattern
        }

        // Check the wave for sinusoidal pattern
        let sinusoid = self.construct_cosine_wave(minima_idx, wave_length);
        let sinusoidness = self.calculate_correlation(&sinusoid);

        if sinusoidness < self.config.sinusoidness_threshold {
            return (false, peak_z_score_amplitude, sinusoidness);
        }

        // If the wave meets the criteria, output the confidence value
        return (true, peak_z_score_amplitude, sinusoidness);
    }

    /// Finds the index of the minimum value within the ongoing_wave_z_scores vector, which represents the peak of the wave.
    fn find_wave_minima(&self) -> usize {
        self.ongoing_wave_z_scores
            .iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap())
            .map(|(idx, _)| idx)
            .unwrap_or(0)
    }

    /// Constructs a cosine wave that matches the frequency and amplitude of the detected wave.
    fn construct_cosine_wave(&self, peak_idx: usize, wave_length: usize) -> Vec<f64> {
        let frequency = 1.0 / (wave_length as f64 / 2.0); // Calculate the frequency based on the wave length
        let amplitude = self.ongoing_wave_z_scores[peak_idx]; // Use the amplitude at the peak index
        (0..wave_length)
            .map(|i| amplitude * (i as f64 * 2.0 * std::f64::consts::PI * frequency).cos())
            .collect()
    }

    /// Calculates the correlation between the ongoing_wave_z_scores and a generated sinusoid to check for pattern match.
    fn calculate_correlation(&self, sinusoid: &Vec<f64>) -> f64 {
        let mean_wave = self.ongoing_wave_z_scores.iter().sum::<f64>()
            / self.ongoing_wave_z_scores.len() as f64;
        let mean_sinusoid = sinusoid.iter().sum::<f64>() / sinusoid.len() as f64;

        let covariance: f64 = self
            .ongoing_wave_z_scores
            .iter()
            .zip(sinusoid.iter())
            .map(|(&x, &y)| (x - mean_wave) * (y - mean_sinusoid))
            .sum();

        let std_dev_wave = (self
            .ongoing_wave_z_scores
            .iter()
            .map(|&x| (x - mean_wave).powi(2))
            .sum::<f64>()
            / self.ongoing_wave_z_scores.len() as f64)
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
