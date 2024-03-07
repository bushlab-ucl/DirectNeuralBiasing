pub struct SlowWaveDetector {
    pub refractory_period: usize,
    pub refractory_samples_to_skip: usize,
    pub threshold_sinusoid: f64,
    pub absolute_min_threshold: f64,
    pub absolute_max_threshold: f64,
    ongoing_wave: Vec<f64>,
    ongoing_wave_idx: Vec<usize>,
    pub detected_waves_idx: Vec<Vec<usize>>,
}

impl SlowWaveDetector {
    pub fn new(
        refractory_period: usize,
        threshold_sinusoid: f64,
        min_threshold_signal: f64, // not sure this is right
        max_threshold_signal: f64, // not sure this is right
    ) -> Self {
        SlowWaveDetector {
            refractory_period,
            refractory_samples_to_skip: 0,
            threshold_sinusoid,
            absolute_min_threshold: min_threshold_signal,
            absolute_max_threshold: max_threshold_signal,
            ongoing_wave: Vec::new(),
            ongoing_wave_idx: Vec::new(),
            detected_waves_idx: Vec::new(),
        }
    }

    pub fn process_sample(
        &mut self,
        sample: f64,
        current_index: usize,
        prev_sample: f64,
        mean: f64,
        std_dev: f64,
    ) -> Option<Vec<usize>> {
        if self.refractory_samples_to_skip > 0 {
            self.refractory_samples_to_skip -= 1;
            return None;
        }

        let crossed_zero = sample > 0.0 && prev_sample <= 0.0;
        if crossed_zero {
            let detected = self.detect_slow_wave();
            if detected {
                self.refractory_samples_to_skip = self.refractory_period;
                let indices = self.ongoing_wave_idx.clone();
                self.ongoing_wave.clear();
                self.ongoing_wave_idx.clear();
                return Some(indices);
            }
        } else {
            self.ongoing_wave.push(sample);
            self.ongoing_wave_idx.push(current_index);
        }

        None
    }

    fn detect_slow_wave(&mut self) -> bool {
        let minima_idx = self.find_wave_minima(&self.ongoing_wave);
        // let maxima_idx = self.find_wave_maxima(&self.ongoing_wave);

        let wave_length = self.ongoing_wave.len();

        let amplitude = self.ongoing_wave[minima_idx].abs();
        if amplitude > self.absolute_min_threshold && amplitude < self.absolute_max_threshold {
            let sinusoid = self.construct_cosine_wave(minima_idx, wave_length);
            let correlation = self.calculate_correlation(&self.ongoing_wave, &sinusoid);

            if correlation > self.threshold_sinusoid {
                // Detected slow wave
                self.refractory_samples_to_skip = self.refractory_period;
                return true;
            }
        }

        false
    }

    fn find_wave_minima(&self, wave: &Vec<f64>) -> usize {
        wave.iter()
            .enumerate()
            .min_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap())
            .map(|(idx, _)| idx)
            .unwrap_or(0)
    }

    // fn find_wave_maxima(&self, wave: &Vec<f64>) -> usize {
    //     wave.iter()
    //         .enumerate()
    //         .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap())
    //         .map(|(idx, _)| idx)
    //         .unwrap_or(0)
    // }

    fn construct_cosine_wave(&self, peak_idx: usize, wave_length: usize) -> Vec<f64> {
        let frequency = 1.0 / (wave_length as f64 / 2.0);
        (0..wave_length)
            .map(|i| {
                let amplitude = self.ongoing_wave[peak_idx];
                amplitude * (i as f64 * 2.0 * std::f64::consts::PI * frequency).cos()
            })
            .collect()
    }

    fn calculate_correlation(&self, wave: &Vec<f64>, sinusoid: &Vec<f64>) -> f64 {
        let mean_wave = wave.iter().sum::<f64>() / wave.len() as f64;
        let mean_sinusoid = sinusoid.iter().sum::<f64>() / sinusoid.len() as f64;

        let covariance: f64 = wave
            .iter()
            .zip(sinusoid.iter())
            .map(|(&x, &y)| (x - mean_wave) * (y - mean_sinusoid))
            .sum();

        let std_dev_wave =
            (wave.iter().map(|&x| (x - mean_wave).powi(2)).sum::<f64>() / wave.len() as f64).sqrt();
        let std_dev_sinusoid = (sinusoid
            .iter()
            .map(|&x| (x - mean_sinusoid).powi(2))
            .sum::<f64>()
            / sinusoid.len() as f64)
            .sqrt();

        covariance / (std_dev_wave * std_dev_sinusoid)
    }
}
