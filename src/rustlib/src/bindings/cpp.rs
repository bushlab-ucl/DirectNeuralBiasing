use crate::processing::detectors::threshold::{ThresholdDetector, ThresholdDetectorConfig};
use crate::processing::detectors::wave_peak::{WavePeakDetector, WavePeakDetectorConfig};
use crate::processing::filters::bandpass::{BandPassFilter, BandPassFilterConfig};
use crate::processing::signal_processor::{SignalProcessor, SignalProcessorConfig};
use crate::processing::triggers::pulse::{PulseTrigger, PulseTriggerConfig};

// use std::collections::HashMap;
use std::ffi::CString;
use std::os::raw::c_char;
use std::os::raw::c_void;
// use std::ptr;

#[repr(C)]
pub struct SignalProcessorFFI {
    processor: SignalProcessor,
    context_buffer: VecDeque<f64>,
    context_size: usize,
}

impl SignalProcessorFFI {
    pub fn new(verbose: bool, fs: f64, channel: usize) -> Self {
        let config = SignalProcessorConfig {
            verbose,
            fs,
            channel,
        };
        Self {
            processor: SignalProcessor::new(config),
            context_buffer: VecDeque::with_capacity(4096 + 4000), // buffer_size + 2*context_size
            context_size: 2000,
        }
    }
}

#[no_mangle]
pub extern "C" fn create_signal_processor(verbose: bool, fs: f64, channel: usize) -> *mut c_void {
    let config = SignalProcessorConfig {
        verbose,
        fs,
        channel,
    };
    let processor = SignalProcessor::new(config);
    let boxed_processor = Box::new(SignalProcessorFFI { processor });
    Box::into_raw(boxed_processor) as *mut c_void
}

#[no_mangle]
pub extern "C" fn delete_signal_processor(processor_ptr: *mut c_void) {
    if !processor_ptr.is_null() {
        unsafe {
            drop(Box::from_raw(processor_ptr as *mut SignalProcessorFFI));
        }
    }
}

#[no_mangle]
pub extern "C" fn add_filter(
    processor_ptr: *mut c_void,
    id: *const c_char,
    f_low: f64,
    f_high: f64,
    fs: f64,
) {
    let processor = unsafe { &mut *(processor_ptr as *mut SignalProcessorFFI) };
    let id_str = unsafe { CString::from_raw(id as *mut c_char) }
        .into_string()
        .unwrap();
    let config = BandPassFilterConfig {
        id: id_str,
        f_low,
        f_high,
        fs,
    };
    let filter = BandPassFilter::new(config);
    processor.processor.add_filter(Box::new(filter));
}

#[no_mangle]
pub extern "C" fn add_threshold_detector(
    processor_ptr: *mut c_void,
    id: *const c_char,
    filter_id: *const c_char,
    z_score_threshold: f64,
    buffer_size: usize,
    sensitivity: f64,
) {
    let processor = unsafe { &mut *(processor_ptr as *mut SignalProcessorFFI) };
    let id_str = unsafe { CString::from_raw(id as *mut c_char) }
        .into_string()
        .unwrap();
    let filter_id_str = unsafe { CString::from_raw(filter_id as *mut c_char) }
        .into_string()
        .unwrap();
    let config = ThresholdDetectorConfig {
        id: id_str,
        filter_id: filter_id_str,
        z_score_threshold,
        buffer_size,
        sensitivity,
    };
    let detector = ThresholdDetector::new(config);
    processor.processor.add_detector(Box::new(detector));
}

#[no_mangle]
pub extern "C" fn add_wave_peak_detector(
    processor_ptr: *mut c_void,
    id: *const c_char,
    filter_id: *const c_char,
    z_score_threshold: f64,
    sinusoidness_threshold: f64,
    check_sinusoidness: bool,
    wave_polarity: *const c_char,
    min_wave_length_ms: f64, // Use f64 directly instead of Option<f64> for C compatibility
    max_wave_length_ms: f64, // Use f64 directly instead of Option<f64> for C compatibility
) {
    let processor = unsafe { &mut *(processor_ptr as *mut SignalProcessorFFI) };
    let id_str = unsafe { CString::from_raw(id as *mut c_char) }
        .into_string()
        .unwrap();
    let filter_id_str = unsafe { CString::from_raw(filter_id as *mut c_char) }
        .into_string()
        .unwrap();
    let wave_polarity_str = unsafe { CString::from_raw(wave_polarity as *mut c_char) }
        .into_string()
        .unwrap();

    // Use sentinel values (-1.0 or NAN) to indicate the absence of a value instead of Option<f64>
    let min_wave_length_ms = if min_wave_length_ms < 0.0 {
        None
    } else {
        Some(min_wave_length_ms)
    };
    let max_wave_length_ms = if max_wave_length_ms < 0.0 {
        None
    } else {
        Some(max_wave_length_ms)
    };

    let config = WavePeakDetectorConfig {
        id: id_str,
        filter_id: filter_id_str,
        z_score_threshold,
        sinusoidness_threshold,
        check_sinusoidness,
        wave_polarity: wave_polarity_str,
        min_wave_length_ms,
        max_wave_length_ms,
    };
    let detector = WavePeakDetector::new(config);
    processor.processor.add_detector(Box::new(detector));
}

#[no_mangle]
pub extern "C" fn add_pulse_trigger(
    processor_ptr: *mut c_void,
    id: *const c_char,
    activation_detector_id: *const c_char,
    inhibition_detector_id: *const c_char,
    inhibition_cooldown_ms: f64,
    pulse_cooldown_ms: f64,
) {
    let processor = unsafe { &mut *(processor_ptr as *mut SignalProcessorFFI) };
    let id_str = unsafe { CString::from_raw(id as *mut c_char) }
        .into_string()
        .unwrap();
    let activation_detector_id_str =
        unsafe { CString::from_raw(activation_detector_id as *mut c_char) }
            .into_string()
            .unwrap();
    let inhibition_detector_id_str =
        unsafe { CString::from_raw(inhibition_detector_id as *mut c_char) }
            .into_string()
            .unwrap();
    let config = PulseTriggerConfig {
        id: id_str,
        activation_detector_id: activation_detector_id_str,
        inhibition_detector_id: inhibition_detector_id_str,
        inhibition_cooldown_ms,
        pulse_cooldown_ms,
    };
    let trigger = PulseTrigger::new(config);
    processor.processor.add_trigger(Box::new(trigger));
}

#[no_mangle]
pub extern "C" fn reset_index(processor_ptr: *mut c_void) {
    let processor = unsafe { &mut *(processor_ptr as *mut SignalProcessorFFI) };
    processor.processor.index = 0;
}

#[no_mangle]
pub extern "C" fn run_chunk(
    processor_ptr: *mut c_void,
    data: *const f64,
    length: usize,
) -> *mut c_void {
    let processor = unsafe { &mut *(processor_ptr as *mut SignalProcessorFFI) };
    let data_slice = unsafe { std::slice::from_raw_parts(data, length) };
    
    // Add new data to context buffer
    processor.context_buffer.extend(data_slice);
    
    // Trim old context if buffer gets too large
    while processor.context_buffer.len() > length + (processor.context_size * 2) {
        processor.context_buffer.pop_front();
    }
    
    // Process with context
    let (_output, trigger_timestamp_option) = 
        processor.processor.run_chunk(processor.context_buffer.make_contiguous().to_vec());
    
    if let Some(trigger_timestamp) = trigger_timestamp_option {
        // Allocate memory for the timestamp and return it
        let result_ptr = Box::into_raw(Box::new(trigger_timestamp));
        return result_ptr as *mut c_void;
    }
    std::ptr::null_mut()
}

// #[no_mangle]
// pub extern "C" fn run_chunk(
//     processor_ptr: *mut c_void,
//     data: *const f64,
//     length: usize,
// ) -> *mut c_void {
//     let processor = unsafe { &mut *(processor_ptr as *mut SignalProcessorFFI) };
//     let data_slice = unsafe { std::slice::from_raw_parts(data, length) };
//     let result = processor.processor.run_chunk(data_slice.to_vec());

//     // Serialize the result into a vector of HashMaps
//     let mut output = Vec::new();
//     for item in result {
//         let mut map = HashMap::new();
//         for (key, value) in item {
//             map.insert(key.to_string(), value);
//         }
//         output.push(map);
//     }

//     let boxed_output = Box::new(output);
//     Box::into_raw(boxed_output) as *mut c_void
// }
