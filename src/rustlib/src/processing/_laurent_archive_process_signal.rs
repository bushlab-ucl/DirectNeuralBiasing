use crate::filters::bandpass::BandPassFilter;
use pyo3::prelude::*;
use std::os::raw::c_void;

use std::fs::OpenOptions;
use std::io::{Result, Write};

fn log_to_file(msg: &str) -> Result<()> {
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open("log.txt")?;

    writeln!(file, "{}", msg)?;
    Ok(())
}

// -----------------------------------------------------------------------------
// RUST CORE LOGIC
// -----------------------------------------------------------------------------

struct Filter {
    filter: BandPassFilter,
    sum: f64,
    count: usize,
    min_threshold_signal: f64,
    max_threshold_signal: f64,
    mean: f64,
    sum_of_squares: f64,
    std_dev: f64,
    filtered_sample: f64,
    prev_sample: f64,
    samples_since_zero_crossing: usize,
    current_index: usize,
    ongoing_wave: Vec<f64>,
    ongoing_wave_idx: Vec<usize>,
    detected_waves_idx: Vec<Vec<usize>>,
    refractory_period: usize,
    refractory_samples_to_skip: usize,
    delay_to_up_state: usize,
    absolute_min_threshold: f64,
    absolute_max_threshold: f64,
    threshold_sinusoid: f64,
    logging: bool,
}

impl Filter {
    pub fn process_sample(&mut self, sample: f64) {
        // Apply bandpass filter to the sample

        if self.logging {
            let formatted_message = format!("{}, {}", self.current_index, sample);
            log_to_file(&formatted_message).expect("Failed to write to log file");
        }

        self.filtered_sample = self.filter.filter_sample(sample);

        if self.refractory_samples_to_skip > 0 {
            self.refractory_samples_to_skip -= 1;
            return;
        }

        // Update statistics
        self.update_statistics();

        // Check for zero crossings or other criteria to detect wave beginnings/ends
        if self.detect_upwards_zero_crossings() {
            // If an upwards zero-crossing is detected, see if it's a slow wave
            if self.detect_slow_wave() {
                self.detected_waves_idx.push(self.ongoing_wave_idx.clone());
                // do stuff for preparing pulse ?
            }
            self.ongoing_wave.clear(); // Reset for the next wave
            self.ongoing_wave_idx.clear();
        } else {
            // If no upwards zero-crossing is detected, accumulate the sample
            self.ongoing_wave.push(self.filtered_sample);
            self.ongoing_wave_idx.push(self.current_index);
        }

        // prepare for next sample
        self.prev_sample = self.filtered_sample;
    }

    // Method to update the power and z-score calculations
    fn update_statistics(&mut self) {
        self.sum += self.filtered_sample;
        self.sum_of_squares += self.filtered_sample.powi(2);
        self.count += 1;

        self.mean = self.sum / self.count as f64;
        self.std_dev = ((self.sum_of_squares / self.count as f64) - self.mean.powi(2)).sqrt();

        self.absolute_min_threshold = self.calculate_threshold(self.min_threshold_signal as u8);
        self.absolute_max_threshold = self.calculate_threshold(self.max_threshold_signal as u8);
    }

    fn calculate_z_score(&self) -> f64 {
        (self.filtered_sample - self.mean) / self.std_dev
    }

    fn calculate_threshold(&mut self, percentile: u8) -> f64 {
        self.mean + self.std_dev * (percentile as f64 / 100.0)
    }

    fn detect_upwards_zero_crossings(&mut self) -> bool {
        if self.filtered_sample > 0.0 && self.prev_sample <= 0.0 {
            self.samples_since_zero_crossing = 0;
            true
        } else {
            self.samples_since_zero_crossing += 1;
            false
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

// -----------------------------------------------------------------------------
// PY03 PYTHON LOGIC
// -----------------------------------------------------------------------------

#[pyclass]
pub struct PyFilter {
    state: Filter,
}

#[pymethods]
impl PyFilter {
    #[new]
    pub fn new(
        f0_l: f64,
        f0_h: f64,
        fs: f64,
        min_threshold_signal: f64,
        max_threshold_signal: f64,
        refractory_period: usize,
        delay_to_up_state: usize,
        threshold_sinusoid: f64,
        logging: bool,
    ) -> Self {
        let bounds: Vec<f64> = vec![f0_l, f0_h];
        let filter = BandPassFilter::with_bounds(bounds, fs);
        PyFilter {
            state: Filter {
                filter,
                sum: 0.0,
                count: 0,
                min_threshold_signal,
                max_threshold_signal,
                mean: 0.0,
                sum_of_squares: 0.0,
                std_dev: 1.0,
                filtered_sample: 0.0,
                prev_sample: 0.0,
                samples_since_zero_crossing: 0,
                current_index: 0,
                ongoing_wave: Vec::new(),
                ongoing_wave_idx: Vec::new(),
                detected_waves_idx: Vec::new(),
                refractory_period,
                refractory_samples_to_skip: 0,
                delay_to_up_state,
                absolute_min_threshold: 0.0,
                absolute_max_threshold: 0.0,
                threshold_sinusoid,
                logging,
            },
        }
    }

    pub fn filter_signal(&mut self, data: Vec<f64>) -> PyResult<(Vec<f64>, Vec<Vec<usize>>)> {
        let mut filtered_signal = Vec::with_capacity(data.len());
        for (idx, &sample) in data.iter().enumerate() {
            self.state.current_index = idx;
            self.state.process_sample(sample);
            filtered_signal.push(self.state.filtered_sample);
        }
        Ok((filtered_signal, self.state.detected_waves_idx.clone()))
    }
}

// -----------------------------------------------------------------------------
// C++ FFI LOGIC
// -----------------------------------------------------------------------------

#[no_mangle]
pub extern "C" fn create_filter(
    f0_l: f64,
    f0_h: f64,
    fs: f64,
    min_threshold_signal: f64,
    max_threshold_signal: f64,
    refractory_period: usize,
    delay_to_up_state: usize,
    threshold_sinusoid: f64,
    logging: bool,
) -> *mut c_void {
    let bounds: Vec<f64> = vec![f0_l, f0_h];
    let filter = BandPassFilter::with_bounds(bounds, fs);
    let state = Filter {
        filter,
        sum: 0.0,
        count: 0,
        min_threshold_signal,
        max_threshold_signal,
        mean: 0.0,
        sum_of_squares: 0.0,
        std_dev: 1.0,
        filtered_sample: 0.0,
        prev_sample: 0.0,
        samples_since_zero_crossing: 0,
        current_index: 0,
        ongoing_wave: Vec::new(),
        ongoing_wave_idx: Vec::new(),
        detected_waves_idx: Vec::new(),
        refractory_period,
        refractory_samples_to_skip: 0,
        delay_to_up_state,
        absolute_min_threshold: 0.0,
        absolute_max_threshold: 0.0,
        threshold_sinusoid,
        logging,
    };
    let boxed_state = Box::new(state);
    Box::into_raw(boxed_state) as *mut c_void
}

#[no_mangle]
pub extern "C" fn delete_filter(filter_ptr: *mut c_void) {
    if filter_ptr.is_null() {
        return;
    }
    unsafe {
        drop(Box::from_raw(filter_ptr as *mut Filter));
    }
}

#[no_mangle]
pub extern "C" fn process_single_sample(filter_ptr: *mut c_void, sample: f64) -> bool {
    if filter_ptr.is_null() {
        return false;
    }
    let state = unsafe { &mut *(filter_ptr as *mut Filter) };

    state.process_sample(sample);
    // let z_score = state.calculate_z_score();

    let above_min_threshold = state.filtered_sample > state.min_threshold_signal;
    let below_max_threshold = state.filtered_sample < state.max_threshold_signal;

    above_min_threshold & below_max_threshold
}

#[no_mangle]
pub extern "C" fn process_sample_chunk(
    filter_ptr: *mut c_void,
    data: *mut f64,
    length: usize,
) -> bool {
    if filter_ptr.is_null() {
        return false;
    }
    let state = unsafe { &mut *(filter_ptr as *mut Filter) };
    let data_slice = unsafe { std::slice::from_raw_parts(data, length) };

    let mut threshold_exceeded = false;
    for &sample in data_slice {
        state.process_sample(sample);
        // let z_score = state.calculate_z_score();

        let above_min_threshold = state.filtered_sample > state.min_threshold_signal;
        let below_max_threshold = state.filtered_sample < state.max_threshold_signal;

        if above_min_threshold & below_max_threshold {
            threshold_exceeded = true;
            break;
        }
    }

    threshold_exceeded
}
