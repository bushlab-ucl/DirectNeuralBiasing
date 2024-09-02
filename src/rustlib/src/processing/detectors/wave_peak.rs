use super::{DetectorInstance, Statistics};
use crate::processing::signal_processor::SignalProcessorConfig;

use std::collections::HashMap;

pub struct WavePeakDetectorConfig {
    pub id: String,
    pub filter_id: String,
    pub z_score_threshold: f64,
    pub sinusoidness_threshold: f64,
    pub check_sinusoidness: bool,
    pub wave_polarity: String, // "upwave" or "downwave"
}

pub struct Keys {
    raw_key: &'static str,
    filter_key: &'static str,
    detected: &'static str,
    wave_start_index: &'static str,
    wave_end_index: &'static str,
    predicted_next_maxima_index: &'static str,
    peak_z_score_amplitude: &'static str,
    sinusoidness: &'static str,
    statistics_z_score: &'static str,
}

pub struct WavePeakDetector {
    config: WavePeakDetectorConfig,
    statistics: Statistics,
    last_sample: f64,
    is_wave: bool,
    wave_direction: i32,
    ongoing_wave_z_scores: Vec<f64>,
    ongoing_wave_raw: Vec<f64>,
    wave_start_index: Option<usize>,
    wave_end_index: Option<usize>,
    predicted_next_maxima_index: Option<usize>,
    keys: Keys,
}

impl WavePeakDetector {
    pub fn new(config: WavePeakDetectorConfig) -> Self {
        let keys = Keys {
            raw_key: Box::leak(format!("global:raw_sample").into_boxed_str()),
            filter_key: Box::leak(
                format!("filters:{}:filtered_sample", config.filter_id).into_boxed_str(),
            ),
            detected: Box::leak(format!("detectors:{}:detected", config.id).into_boxed_str()),
            wave_start_index: Box::leak(
                format!("detectors:{}:wave_start_index", config.id).into_boxed_str(),
            ),
            wave_end_index: Box::leak(
                format!("detectors:{}:wave_end_index", config.id).into_boxed_str(),
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

        let wave_direction = match config.wave_polarity.as_str() {
            "upwave" => 1,
            "downwave" => -1,
            _ => 0, // should give error
        };

        WavePeakDetector {
            config,
            statistics: Statistics::new(),
            last_sample: 0.0,
            is_wave: false,
            wave_direction,
            ongoing_wave_z_scores: Vec::new(),
            ongoing_wave_raw: Vec::new(),
            wave_start_index: None,
            wave_end_index: None,
            predicted_next_maxima_index: None,
            keys,
        }
    }
}

impl DetectorInstance for WavePeakDetector {
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
        // Retrieve the raw and filtered samples from the results
        let raw_sample = results.get(self.keys.raw_key).cloned().unwrap_or_default();
        let filtered_sample = results
            .get(self.keys.filter_key)
            .cloned()
            .unwrap_or_default();

        // Update statistics with the new filtered sample
        self.statistics.update_statistics(filtered_sample);

        // Check if a directed zero-crossing has occurred based on wave polarity
        if self.check_directed_zero_crossing(self.last_sample, filtered_sample) {
            self.handle_wave_transition(index);
        }

        // Store the ongoing wave's raw vals and z-scores if currently tracking a wave
        if self.is_wave {
            self.ongoing_wave_z_scores.push(self.statistics.z_score);
            self.ongoing_wave_raw.push(raw_sample);
        }

        // If end of wave is detected, process the collected wave data
        if !self.is_wave && !self.ongoing_wave_z_scores.is_empty() {
            self.analyze_and_output_wave_data(results, index);
            self.clear_wave_data();
        }

        // Always return z score
        results.insert(self.keys.statistics_z_score, self.statistics.z_score);

        // Always update the last sample
        self.last_sample = filtered_sample;
    }
}

impl WavePeakDetector {
    // Check if a zero-crossing has occurred based on wave polarity
    fn check_directed_zero_crossing(&self, last_sample: f64, current_sample: f64) -> bool {
        let is_upcrossing = last_sample <= 0.0 && current_sample > 0.0;
        let is_downcrossing = last_sample >= 0.0 && current_sample < 0.0;

        match self.config.wave_polarity.as_ref() {
            "upwave" => {
                if self.is_wave {
                    is_downcrossing // End of upwave detected
                } else {
                    is_upcrossing // Start of upwave detected
                }
            }
            "downwave" => {
                if self.is_wave {
                    is_upcrossing // End of downwave detected
                } else {
                    is_downcrossing // Start of downwave detected
                }
            }
            _ => false,
        }
    }

    // Handles the transition of wave based on zero-crossing detection
    fn handle_wave_transition(&mut self, index: usize) {
        if self.is_wave {
            // Transition from wave to non-wave state
            self.is_wave = false;
            self.wave_end_index = Some(index);
        } else {
            // Transition from non-wave to wave state
            self.is_wave = true;
            self.wave_start_index = Some(index);
        }
    }

    // Clears the collected data after wave analysis
    fn clear_wave_data(&mut self) {
        self.ongoing_wave_z_scores.clear();
        self.ongoing_wave_raw.clear();
        self.wave_start_index = None;
        self.wave_end_index = None;
        self.predicted_next_maxima_index = None;
    }

    // Predicts the next wave maxima based on the current wave's length
    fn predict_next_maxima(&mut self, index: usize) {
        let half_period = self.ongoing_wave_z_scores.len() / 2;
        self.predicted_next_maxima_index = Some(index + half_period);
    }

    // Analyzes the wave data, outputs to results, and predicts next maxima
    fn analyze_and_output_wave_data(
        &mut self,
        results: &mut HashMap<&'static str, f64>,
        index: usize,
    ) {
        let (detected, peak_z_score_amplitude, sinusoidness) = self.analyze_wave();
        if detected {
            self.predict_next_maxima(index);
            results.insert(self.keys.detected, 1.0);

            results.insert(
                self.keys.wave_start_index,
                self.wave_start_index.map_or(-1.0, |v| v as f64),
            );

            results.insert(
                self.keys.wave_end_index,
                self.wave_end_index.map_or(-1.0, |v| v as f64),
            );

            results.insert(
                self.keys.predicted_next_maxima_index,
                self.predicted_next_maxima_index.map_or(-1.0, |v| v as f64),
            );
        } else {
            results.insert(self.keys.detected, 0.0);
        }

        // Output additional wave information
        results.insert(self.keys.peak_z_score_amplitude, peak_z_score_amplitude);
        if self.config.check_sinusoidness {
            results.insert(self.keys.sinusoidness, sinusoidness);
        }
    }

    /// Analyzes the collected wave data to determine if it meets the criteria for a slow wave.
    fn analyze_wave(&mut self) -> (bool, f64, f64) {
        let wave_length = self.ongoing_wave_z_scores.len();
        if wave_length < 4 {
            // Minimum wave length for analysis - 4 samples is arbitrary
            return (false, -1.0, -1.0); // -1 indicates no sinusoidal pattern
        }

        // Find the minimum amplitude within the wave to define the peak
        let z_score_minima_idx = self.find_wave_minima(self.ongoing_wave_z_scores.clone());
        let raw_minima_idx = self.find_wave_minima(self.ongoing_wave_raw.clone());
        let peak_z_score_amplitude = self.ongoing_wave_z_scores[z_score_minima_idx].abs();

        // Check if the amplitude is above the threshold
        if peak_z_score_amplitude < self.config.z_score_threshold {
            return (false, peak_z_score_amplitude, -1.0); // -1 indicates no sinusoidal pattern
        }

        // Check the wave for sinusoidal pattern if required
        if self.config.check_sinusoidness {
            let sinusoid = self.construct_adjusted_cosine_wave(raw_minima_idx, wave_length);
            let sinusoidness = self.calculate_correlation(&sinusoid);

            if sinusoidness < self.config.sinusoidness_threshold {
                return (false, peak_z_score_amplitude, sinusoidness);
            }
            return (true, peak_z_score_amplitude, sinusoidness);
        }

        // If sinusoidness is not checked, return true based on amplitude
        return (true, peak_z_score_amplitude, -1.0);
    }

    fn find_wave_minima(&self, wave: Vec<f64>) -> usize {
        wave.iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .map(|(idx, _)| idx)
            .unwrap_or(0)
    }

    /// Constructs a cosine wave that matches the frequency, polarity, and amplitude of the detected wave.
    fn construct_adjusted_cosine_wave(&self, peak_idx: usize, wave_length: usize) -> Vec<f64> {
        let amplitude = self.ongoing_wave_raw[peak_idx]; // Use the amplitude at the peak index

        // Ensure the total length matches the wave_length
        let first_half_length = peak_idx + 1;
        let second_half_length = wave_length - first_half_length;

        // Determine the sign for the cosine wave based on wave polarity
        let sign = if self.wave_direction == 1 { 1.0 } else { -1.0 };

        // Construct the first half-wave (pi/2 to pi)
        let first_half_wave: Vec<f64> = (0..first_half_length)
            .map(|i| {
                let t = std::f64::consts::PI / 2.0
                    + (i as f64 / (first_half_length as f64)) * (std::f64::consts::PI / 2.0);
                sign * amplitude * t.cos() // Apply the sign to account for wave polarity
            })
            .collect();

        // Construct the second half-wave (pi to 3pi/2)
        let second_half_wave: Vec<f64> = (0..second_half_length)
            .map(|i| {
                let t = std::f64::consts::PI
                    + (i as f64 / (second_half_length as f64)) * (std::f64::consts::PI / 2.0);
                sign * amplitude * t.cos() // Apply the sign to account for wave polarity
            })
            .collect();

        // Combine the two half-waves
        [first_half_wave, second_half_wave].concat()
    }

    /// Calculates the correlation between the ongoing_wave_z_scores and a generated sinusoid to check for pattern match.
    fn calculate_correlation(&self, sinusoid: &Vec<f64>) -> f64 {
        // Calculate means
        let mean_wave =
            self.ongoing_wave_raw.iter().sum::<f64>() / self.ongoing_wave_raw.len() as f64;
        let mean_sinusoid = sinusoid.iter().sum::<f64>() / sinusoid.len() as f64;

        // Calculate covariance
        let covariance: f64 = self
            .ongoing_wave_raw
            .iter()
            .zip(sinusoid.iter())
            .map(|(&x, &y)| (x - mean_wave) * (y - mean_sinusoid))
            .sum::<f64>()
            / self.ongoing_wave_raw.len() as f64;

        // Calculate standard deviations
        let std_dev_wave = (self
            .ongoing_wave_raw
            .iter()
            .map(|&x| (x - mean_wave).powi(2))
            .sum::<f64>()
            / self.ongoing_wave_raw.len() as f64)
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

        // Calculate and return the correlation
        covariance / (std_dev_wave * std_dev_sinusoid)
    }
}
