use crate::filters::bandpass::BandPassFilter;
use std::os::raw::c_void;

struct FilterState {
    filter: BandPassFilter,
    sum: f64,
    count: usize,
    threshold: f64,
    mean: f64,
    sum_of_squares: f64,
    std_dev: f64,
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
}

#[no_mangle]
pub extern "C" fn create_filter_state(f0: f64, fs: f64, threshold: f64) -> *mut c_void {
    let filter = BandPassFilter::butterworth(f0, fs);
    let state = FilterState {
        filter,
        sum: 0.0,
        count: 0,
        threshold,
        mean: 0.0,
        sum_of_squares: 0.0,
        std_dev: 1.0, // Starting with a default value to avoid division by zero
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
    z_score > state.threshold
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
