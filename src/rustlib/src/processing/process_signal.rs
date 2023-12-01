use crate::filters::bandpass::BandPassFilter;
use pyo3::prelude::*;
// use std::os::raw::c_void;

// -----------------------------------------------------------------------------
// RUST CORE LOGIC
// -----------------------------------------------------------------------------

struct FilterState {
    filter: BandPassFilter,
    sum: f64,
    count: usize,
    threshold: f64,
    mean: f64,
    sum_of_squares: f64,
    std_dev: f64,
    filtered_sample: f64,
    prev_sample: f64,
    samples_since_zero_crossing: usize,
    current_index: usize,
    ongoing_wave: Vec<f64>,
    detected_waves: Vec<Vec<f64>>,
}

impl FilterState {
    pub fn process_sample(&mut self, sample: f64) {
        // Apply bandpass filter to the sample
        self.filtered_sample = self.filter.filter_sample(sample);

        // Update statistics
        self.update_statistics(self.filtered_sample);

        // Check for zero crossings or other criteria to detect wave beginnings/ends
        if self.detect_zero_crossings(self.filtered_sample) {
            // If an upwards zero-crossing is detected, see if it's a slow wave
            if self.detect_slow_wave() {
                // do something
            }
            self.ongoing_wave.clear(); // Reset for the next wave
        } else {
            // If no upwards zero-crossing is detected, accumulate the sample
            self.ongoing_wave.push(self.filtered_sample);
        }
    }

    // Method to update the power and z-score calculations
    fn update_statistics(&mut self, sample: f64) {
        self.sum += sample;
        self.sum_of_squares += sample.powi(2);
        self.count += 1;

        self.mean = self.sum / self.count as f64;
        self.std_dev = ((self.sum_of_squares / self.count as f64) - self.mean.powi(2)).sqrt();
    }

    fn calculate_z_score(&self, sample: f64) -> f64 {
        (sample - self.mean) / self.std_dev
    }

    fn detect_zero_crossings(&mut self, sample: f64) -> bool {
        if sample < 0.0 && self.prev_sample >= 0.0 {
            let samples_since_zero_crossing = self.samples_since_zero_crossing;
            self.samples_since_zero_crossing = 0;
            true
        } else {
            self.samples_since_zero_crossing += 1;
            false
        }
    }

    // Adapted for real-time processing
    fn detect_slow_wave(&mut self) -> bool {
        if self.detect_sinusoidal() {
            // do something
            true
        } else {
            false
        }
    }

    fn detect_sinusoidal(&mut self) -> bool {
        // construct sinsuoidal wave and convolve with ongoing wave
        let mut sinusoid = Vec::with_capacity(self.ongoing_wave.len());
        for i in 0..self.ongoing_wave.len() {
            sinusoid.push((i as f64 * 2.0 * std::f64::consts::PI / 100.0).sin());
        }
        // let convolved = convolve(&self.ongoing_wave, &sinusoid);
        true
    }
}

// -----------------------------------------------------------------------------
// C++ FFI LOGIC
// -----------------------------------------------------------------------------

// #[no_mangle]
// pub extern "C" fn create_filter_state(
//     f0_l: f64,
//     f0_h: f64,
//     fs: f64,
//     threshold: f64,
// ) -> *mut c_void {
//     let bounds: Vec<f64> = vec![f0_l, f0_h];
//     let filter = BandPassFilter::with_bounds(bounds, fs);
//     let state = FilterState {
//         filter,
//         sum: 0.0,
//         count: 0,
//         threshold,
//         mean: 0.0,
//         sum_of_squares: 0.0,
//         std_dev: 1.0, // Starting with a default value to avoid division by zero
//         prev_sample: 0.0,
//         samples_since_zero_crossing: 0,
//         ongoing_wave: Vec::new(),
//     };
//     let boxed_state = Box::new(state);
//     Box::into_raw(boxed_state) as *mut c_void
// }

// #[no_mangle]
// pub extern "C" fn delete_filter_state(filter_ptr: *mut c_void) {
//     if filter_ptr.is_null() {
//         return;
//     }
//     unsafe {
//         drop(Box::from_raw(filter_ptr as *mut FilterState));
//     }
// }

// #[no_mangle]
// pub extern "C" fn process_single_sample(filter_ptr: *mut c_void, sample: f64) -> bool {
//     if filter_ptr.is_null() {
//         return false;
//     }
//     let state = unsafe { &mut *(filter_ptr as *mut FilterState) };

//     let filtered_sample = state.filter.filter_sample(sample);
//     state.update_statistics(filtered_sample);

//     let z_score = state.calculate_z_score(filtered_sample);
//     let above_threshold = z_score > state.threshold;

//     state.detect_zero_crossings(filtered_sample);

//     above_threshold
// }

// #[no_mangle]
// pub extern "C" fn process_sample_chunk(
//     filter_ptr: *mut c_void,
//     data: *mut f64,
//     length: usize,
// ) -> bool {
//     if filter_ptr.is_null() {
//         return false;
//     }
//     let state = unsafe { &mut *(filter_ptr as *mut FilterState) };
//     let data_slice = unsafe { std::slice::from_raw_parts(data, length) };

//     let mut threshold_exceeded = false;
//     for &sample in data_slice {
//         let filtered_sample = state.filter.filter_sample(sample);
//         state.update_statistics(filtered_sample);

//         let z_score = state.calculate_z_score(filtered_sample);
//         if z_score > state.threshold {
//             threshold_exceeded = true;
//             break;
//         }
//     }

//     threshold_exceeded
// }

// -----------------------------------------------------------------------------
// PY03 PYTHON LOGIC
// -----------------------------------------------------------------------------

#[pyclass]
pub struct PyFilterState {
    state: FilterState,
}

#[pymethods]
impl PyFilterState {
    #[new]
    pub fn new(f0_l: f64, f0_h: f64, fs: f64, threshold: f64) -> Self {
        let bounds: Vec<f64> = vec![f0_l, f0_h];
        let filter = BandPassFilter::with_bounds(bounds, fs);
        PyFilterState {
            state: FilterState {
                filter,
                sum: 0.0,
                count: 0,
                threshold,
                mean: 0.0,
                sum_of_squares: 0.0,
                std_dev: 1.0, // default value to avoid division by zero
                prev_sample: 0.0,
                filtered_sample: 0.0,
                samples_since_zero_crossing: 0,
                ongoing_wave: Vec::new(),
                detected_waves: Vec::new(),
                current_index: 0,
            },
        }
    }

    pub fn filter_signal(&mut self, data: Vec<f64>) -> PyResult<Vec<f64>> {
        let mut filtered_signal = Vec::with_capacity(data.len());
        for &sample in &data {
            self.state.process_sample(sample);
            filtered_signal.push(self.state.filtered_sample);
        }
        Ok(filtered_signal)
    }
}
