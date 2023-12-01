use crate::filters::bandpass::BandPassFilter;
use pyo3::prelude::*;
use std::os::raw::c_void;

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
    prev_sample: f64,
    samples_since_zero_crossing: usize,
}

impl FilterState {
    // Method to update the power and z-score calculations
    pub fn update_statistics(&mut self, sample: f64) {
        self.sum += sample;
        self.sum_of_squares += sample.powi(2);
        self.count += 1;

        self.mean = self.sum / self.count as f64;
        self.std_dev = ((self.sum_of_squares / self.count as f64) - self.mean.powi(2)).sqrt();
    }

    // Method to calculate the z-score for the current sample
    pub fn calculate_z_score(&self, sample: f64) -> f64 {
        (sample - self.mean) / self.std_dev
    }

    // Method to detect zero crossings
    pub fn detect_zero_crossings(&mut self, sample: f64) -> usize {
        if sample < 0.0 && self.prev_sample >= 0.0 {
            let samples_since_zero_crossing = self.samples_since_zero_crossing;
            self.samples_since_zero_crossing = 0;
            return samples_since_zero_crossing;
        } else {
            self.samples_since_zero_crossing += 1;
            return 0;
        }
    }
}

// -----------------------------------------------------------------------------
// C++ FFI LOGIC
// -----------------------------------------------------------------------------

#[no_mangle]
pub extern "C" fn create_filter_state(
    f0_l: f64,
    f0_h: f64,
    fs: f64,
    threshold: f64,
) -> *mut c_void {
    let bounds: Vec<f64> = vec![f0_l, f0_h];
    let filter = BandPassFilter::with_bounds(bounds, fs);
    let state = FilterState {
        filter,
        sum: 0.0,
        count: 0,
        threshold,
        mean: 0.0,
        sum_of_squares: 0.0,
        std_dev: 1.0, // Starting with a default value to avoid division by zero
        prev_sample: 0.0,
        samples_since_zero_crossing: 0,
    };
    let boxed_state = Box::new(state);
    Box::into_raw(boxed_state) as *mut c_void
}

#[no_mangle]
pub extern "C" fn delete_filter_state(filter_ptr: *mut c_void) {
    if filter_ptr.is_null() {
        return;
    }
    unsafe {
        drop(Box::from_raw(filter_ptr as *mut FilterState));
    }
}

#[no_mangle]
pub extern "C" fn process_single_sample(filter_ptr: *mut c_void, sample: f64) -> bool {
    if filter_ptr.is_null() {
        return false;
    }
    let state = unsafe { &mut *(filter_ptr as *mut FilterState) };

    let filtered_sample = state.filter.process_sample(sample);
    state.update_statistics(filtered_sample);

    let z_score = state.calculate_z_score(filtered_sample);
    let above_threshold = z_score > state.threshold;

    state.detect_zero_crossings(filtered_sample);

    above_threshold
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
    let state = unsafe { &mut *(filter_ptr as *mut FilterState) };
    let data_slice = unsafe { std::slice::from_raw_parts(data, length) };

    let mut threshold_exceeded = false;
    for &sample in data_slice {
        let filtered_sample = state.filter.process_sample(sample);
        state.update_statistics(filtered_sample);

        let z_score = state.calculate_z_score(filtered_sample);
        if z_score > state.threshold {
            threshold_exceeded = true;
            break;
        }
    }

    threshold_exceeded
}

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
                samples_since_zero_crossing: 0,
            },
        }
    }

    pub fn filter_signal(&mut self, data: Vec<f64>) -> PyResult<Vec<f64>> {
        let mut filtered_signal = Vec::with_capacity(data.len());
        for &sample in &data {
            let filtered_sample = self.state.filter.process_sample(sample);
            self.state.update_statistics(filtered_sample);
            filtered_signal.push(filtered_sample);
        }
        Ok(filtered_signal)
    }
}
