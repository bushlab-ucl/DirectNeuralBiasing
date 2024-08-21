use super::{DetectorInstance, Statistics};
use crate::processing::signal_processor::SignalProcessorConfig;

use std::collections::HashMap;

pub struct SlowWaveDetectorConfig {
    pub id: String,
    pub filter_id: String,
    pub z_score_threshold: f64,
    pub sinusoidness_threshold: f64,
}

pub struct Keys {
    filter_key: &'static str,
    detected: &'static str,
    downwave_start_index: &'static str,
    downwave_end_index: &'static str,
    predicted_next_maxima_index: &'static str,
    peak_z_score_amplitude: &'static str,
    sinusoidness: &'static str,
    statistics_z_score: &'static str,
}

pub struct SlowWaveDetector {
    config: SlowWaveDetectorConfig,
    statistics: Statistics,
    last_z_score: f64,
    is_downwave: bool,
    ongoing_wave_z_scores: Vec<f64>,
    downwave_start_index: Option<usize>,
    downwave_end_index: Option<usize>,
    predicted_next_maxima_index: Option<usize>,
    keys: Keys,
}

impl SlowWaveDetector {
    pub fn new(config: SlowWaveDetectorConfig) -> Self {
        let keys = Keys {
            filter_key: Box::leak(
                format!("filters:{}:filtered_sample", config.filter_id).into_boxed_str(),
            ),
            detected: Box::leak(format!("detectors:{}:detected", config.id).into_boxed_str()),
            downwave_start_index: Box::leak(
                format!("detectors:{}:downwave_start_index", config.id).into_boxed_str(),
            ),
            downwave_end_index: Box::leak(
                format!("detectors:{}:downwave_end_index", config.id).into_boxed_str(),
            ),
            predicted_next_maxima_index: Box::leak(
                format!("detectors:{}:predicted_next_maxima_index", config.id).into_boxed_str(),
            ),
            peak_z_score_amplitude: Box::leak(
                format!("detectors:{}:peak_z_score_amplitude", config.id).into_boxed_str(),
            ),
            sinusoidness: Box::leak(
                format!("detectors:{}:sinusoidness", config.id).into_boxed_str(),
            ),
            statistics_z_score: Box::leak(
                format!("detectors:{}:statistics:z_score", config.id).into_boxed_str(),
            ),
        };

        SlowWaveDetector {
            config,
            statistics: Statistics::new(),
            last_z_score: 0.0,
            is_downwave: false,
            ongoing_wave_z_scores: Vec::new(),
            downwave_start_index: None,
            downwave_end_index: None,
            predicted_next_maxima_index: None,
            keys,
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
        _global_config: &SignalProcessorConfig,
        results: &mut HashMap<&'static str, f64>,
        index: usize,
    ) {
        // Fetch the filtered sample using a cloned unwrap_or to handle the absence gracefully
        let filtered_sample = results.get(self.keys.filter_key).cloned().unwrap();

        // Update statistics with the new filtered sample
        self.statistics.update_statistics(filtered_sample);

        // Detect start of downwave (zero-crossing from positive to negative)
        if self.last_z_score >= 0.0 && self.statistics.z_score < 0.0 {
            self.is_downwave = true;
            self.downwave_start_index = Some(index);
        }

        // If downwave, store the ongoing wave z_score for analysis
        if self.is_downwave {
            self.ongoing_wave_z_scores.push(self.statistics.z_score);
        }

        // Detect end of ongoing downwave and analyse (zero-crossing from negative to positive)
        if self.is_downwave && self.last_z_score <= 0.0 && self.statistics.z_score > 0.0 {
            self.is_downwave = false;
            self.downwave_end_index = Some(index);

            // Analyze the wave
            let (detected, peak_z_score_amplitude, sinusoidness) = self.analyse_wave();

            // Predict next maxima and output to results
            if detected {
                // Predict the next wave maxima
                let half_period = self.ongoing_wave_z_scores.len() / 2;
                self.predicted_next_maxima_index = Some(index + half_period);

                // Output the detection status and wave index values
                results.insert(self.keys.detected, 1.0);

                results.insert(
                    self.keys.downwave_start_index,
                    self.downwave_start_index.map_or(-1.0, |v| v as f64), // unwrap as -1 if None (should not happen)
                );

                results.insert(
                    self.keys.downwave_end_index,
                    self.downwave_end_index.map_or(-1.0, |v| v as f64), // unwrap as -1 if None (should not happen)
                );

                results.insert(
                    self.keys.predicted_next_maxima_index,
                    self.predicted_next_maxima_index.map_or(-1.0, |v| v as f64), // unwrap as -1 if None (should not happen)
                );
            } else {
                // Output the detection status as zero
                results.insert(self.keys.detected, 0.0);
            }

            // Output the peak amplitude and sinusoidness values
            results.insert(self.keys.peak_z_score_amplitude, peak_z_score_amplitude);

            results.insert(self.keys.sinusoidness, sinusoidness);

            // Clear the ongoing wave data after analysis
            self.ongoing_wave_z_scores.clear();
            self.downwave_start_index = None;
            self.downwave_end_index = None;
        } else {
            // Output the detection status as zero
            results.insert(self.keys.detected, 0.0);
        }

        // Output the z_score value to the results HashMap
        results.insert(self.keys.statistics_z_score, self.statistics.z_score);

        // Update the last sample for zero-crossing detection
        self.last_z_score = self.statistics.z_score;
    }
}

impl SlowWaveDetector {
    /// Analyzes the collected wave data to determine if it meets the criteria for a slow wave.
    fn analyse_wave(&mut self) -> (bool, f64, f64) {
        let wave_length = self.ongoing_wave_z_scores.len();
        if wave_length < 4 {
            // Minimum wave length for analysis - 4 samples is arbitrary
            return (false, -1.0, -1.0); // -1 indicates no sinusoidal pattern
        }

        // Find the minimum amplitude within the wave to define the peak
        let minima_idx = self.find_wave_minima();
        let peak_z_score_amplitude = self.ongoing_wave_z_scores[minima_idx].abs();

        // Check if the amplitude is above the threshold
        if peak_z_score_amplitude < self.config.z_score_threshold {
            return (false, peak_z_score_amplitude, -1.0); // -1 indicates no sinusoidal pattern
        }

        // Check the wave for sinusoidal pattern
        let sinusoid = self.construct_adjusted_cosine_wave(minima_idx, wave_length);
        let sinusoidness = self.calculate_correlation(&sinusoid);

        if sinusoidness < self.config.sinusoidness_threshold {
            return (false, peak_z_score_amplitude, sinusoidness);
        }
        // println!("Detected slow wave!");

        // If the wave meets the criteria, output the confidence value
        return (true, peak_z_score_amplitude, sinusoidness);
    }

    /// Finds the index of the minimum value within the ongoing_wave_z_scores vector, which represents the peak of the wave.
    fn find_wave_minima(&self) -> usize {
        self.ongoing_wave_z_scores
            .iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .map(|(idx, _)| idx)
            .unwrap_or(0)
    }

    // /// Constructs a cosine wave that matches the frequency and amplitude of the detected wave.
    // fn construct_cosine_wave(&self, peak_idx: usize, wave_length: usize) -> Vec<f64> {
    //     let frequency = 1.0 / (wave_length as f64); // Calculate the frequency based on the wave length
    //     let amplitude = self.ongoing_wave_z_scores[peak_idx]; // Use the amplitude at the peak index
    //     (0..wave_length)
    //         .map(|i| {
    //             let phase_shift = std::f64::consts::PI / 2.0; // Phase shift to start from pi/2
    //             amplitude
    //                 * ((i as f64 * 2.0 * std::f64::consts::PI * frequency) + phase_shift).cos()
    //         })
    //         .collect()
    // }

    /// Constructs a cosine wave that matches the frequency and amplitude of the detected wave.
    fn construct_adjusted_cosine_wave(&self, peak_idx: usize, wave_length: usize) -> Vec<f64> {
        let amplitude = self.ongoing_wave_z_scores[peak_idx]; // Use the amplitude at the peak index

        // Ensure the total length matches the wave_length
        let first_half_length = peak_idx + 1;
        let second_half_length = wave_length - first_half_length;

        // Construct the first half-wave (pi/2 to pi)
        let first_half_wave: Vec<f64> = (0..first_half_length)
            .map(|i| {
                let t = std::f64::consts::PI / 2.0
                    + (i as f64 / (first_half_length as f64)) * (std::f64::consts::PI / 2.0);
                -amplitude * t.cos() // Flipping the cosine to match the downwave
            })
            .collect();

        // Construct the second half-wave (pi to 3pi/2)
        let second_half_wave: Vec<f64> = (0..second_half_length)
            .map(|i| {
                let t = std::f64::consts::PI
                    + (i as f64 / (second_half_length as f64)) * (std::f64::consts::PI / 2.0);
                -amplitude * t.cos() // Flipping the cosine to match the upwave
            })
            .collect();

        // Combine the two half-waves
        [first_half_wave, second_half_wave].concat()
    }

    /// Calculates the correlation between the ongoing_wave_z_scores and a generated sinusoid to check for pattern match.
    fn calculate_correlation(&self, sinusoid: &Vec<f64>) -> f64 {
        // Calculate means
        let mean_wave = self.ongoing_wave_z_scores.iter().sum::<f64>()
            / self.ongoing_wave_z_scores.len() as f64;
        let mean_sinusoid = sinusoid.iter().sum::<f64>() / sinusoid.len() as f64;

        // Calculate covariance
        let covariance: f64 = self
            .ongoing_wave_z_scores
            .iter()
            .zip(sinusoid.iter())
            .map(|(&x, &y)| (x - mean_wave) * (y - mean_sinusoid))
            .sum::<f64>()
            / self.ongoing_wave_z_scores.len() as f64;

        // Calculate standard deviations
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

        // Avoid division by zero
        if std_dev_wave == 0.0 || std_dev_sinusoid == 0.0 {
            return 0.0;
        }

        // debug prints
        // Print the cosine wave
        // println!("Cosine wave values: {:?}", sinusoid);
        // Print the z-score waveform
        // println!("Z-score waveform values: {:?}", self.ongoing_wave_z_scores);

        // Calculate and return the correlation
        covariance / (std_dev_wave * std_dev_sinusoid)
    }
}
