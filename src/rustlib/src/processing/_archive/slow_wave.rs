#[derive(Clone)]
pub struct SlowWaveDetectorConfig {
    pub filter_id: String,
    pub refractory_period: usize,
    pub sinusoid_threshold: f64,
    pub absolute_min_threshold: f64,
    pub absolute_max_threshold: f64,
}

pub struct SlowWaveDetector {
    config: SlowWaveDetectorConfig,
    refractory_samples_to_skip: usize,
    ongoing_wave: Vec<f64>,
    ongoing_wave_idx: Vec<usize>,
}

impl SlowWaveDetector {
    pub fn new(config: SlowWaveDetectorConfig) -> Self {
        SlowWaveDetector {
            config,
            refractory_samples_to_skip: 0,
            ongoing_wave: Vec::new(),
            ongoing_wave_idx: Vec::new(),
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
        // Only proceed if not in refractory period
        if self.refractory_samples_to_skip > 0 {
            self.refractory_samples_to_skip -= 1;
            return;
        }

        // Fetch the filtered sample from results
        if let Some(&filtered_sample) =
            results.get(&format!("filters:{}:output", self.config.filter_id))
        {
            let prev_sample = results
                .get(&format!("detectors:{}:last_sample", detector_id))
                .cloned()
                .unwrap_or(0.0);
            results.insert(
                format!("detectors:{}:last_sample", detector_id),
                filtered_sample,
            );

            let mean = results
                .get(&format!("filters:{}:mean", self.config.filter_id))
                .cloned()
                .unwrap_or(0.0);
            let std_dev = results
                .get(&format!("filters:{}:std_dev", self.config.filter_id))
                .cloned()
                .unwrap_or(0.0);

            let crossed_zero = filtered_sample > 0.0 && prev_sample <= 0.0;

            if crossed_zero && self.detect_slow_wave(filtered_sample, mean, std_dev) {
                results.insert(format!("detectors:{}:detected", detector_id), 1.0);
                results.insert(format!("detectors:{}:confidence", detector_id), 100.0); // Arbitrary confidence for example
                self.refractory_samples_to_skip = self.config.refractory_period;
                self.ongoing_wave.clear();
                self.ongoing_wave_idx.clear();
            } else {
                self.ongoing_wave.push(filtered_sample);
                self.ongoing_wave_idx.push(index);
                results.insert(format!("detectors:{}:detected", detector_id), 0.0);
                results.insert(format!("detectors:{}:confidence", detector_id), 0.0);
            }
        }
    }

    fn detect_slow_wave(&mut self) -> bool {
        let minima_idx = self.find_wave_minima(&self.ongoing_wave);
        // let maxima_idx = self.find_wave_maxima(&self.ongoing_wave);

        let wave_length = self.ongoing_wave.len();

        let amplitude = self.ongoing_wave[minima_idx].abs();
        if amplitude > self.absolute_min_threshold && amplitude < self.absolute_max_threshold {
            let sinusoid = self.construct_cosine_wave(minima_idx, wave_length);
            let correlation = self.calculate_correlation(&self.ongoing_wave, &sinusoid);

            if correlation > self.sinusoid_threshold {
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
