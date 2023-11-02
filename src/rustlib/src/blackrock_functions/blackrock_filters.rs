use crate::filters::bandpass::BandPassFilter;

use std::os::raw::c_void;

#[no_mangle]
pub extern "C" fn create_filter(f0: f64, fs: f64) -> *mut c_void {
    let filter = BandPassFilter::butterworth(f0, fs);
    let boxed_filter = Box::new(filter);
    Box::into_raw(boxed_filter) as *mut c_void
}

#[no_mangle]
pub extern "C" fn delete_filter(filter_ptr: *mut c_void) {
    if filter_ptr.is_null() {
        return;
    }
    unsafe {
        drop(Box::from_raw(filter_ptr as *mut BandPassFilter));
    }
}

#[no_mangle]
pub extern "C" fn process_filter_data(filter_ptr: *mut c_void, data: *mut i16, length: usize) {
    if filter_ptr.is_null() || data.is_null() {
        return;
    }
    let filter = unsafe { &mut *(filter_ptr as *mut BandPassFilter) };
    let data_slice = unsafe { std::slice::from_raw_parts_mut(data, length) };

    for val in data_slice {
        let input = *val as f64;
        let output = filter.filter(input);
        *val = output as i16;
    }

    // threshold (doing something like a z score, but keeping track of sum and amount to do it without storing all values)

    // track iterations above threshold (allow some leeway (X) for noise until threshold (Y) where we think it's an SWR)

    // if spike. Output time to file and maybe dump data
}
