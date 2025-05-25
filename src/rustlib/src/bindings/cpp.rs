use crate::processing::signal_processor::SignalProcessor;
use std::collections::VecDeque;
use std::ffi::CString;
use std::os::raw::c_char;
use std::os::raw::c_void;

#[repr(C)]
pub struct SignalProcessorFFI {
    processor: SignalProcessor,
    context_buffer: VecDeque<f64>,
    context_size: usize,
}

impl SignalProcessorFFI {
    pub fn new_from_config(config_path: &str) -> Result<Self, String> {
        let processor = SignalProcessor::from_config_file(config_path)?;

        Ok(Self {
            processor,
            context_buffer: VecDeque::with_capacity(4096 + 4000),
            context_size: 2000,
        })
    }
}

// Remove the old create_signal_processor function and replace with config-based version
#[no_mangle]
pub extern "C" fn create_signal_processor_from_config(config_path: *const c_char) -> *mut c_void {
    if config_path.is_null() {
        eprintln!("Error: config_path is null");
        return std::ptr::null_mut();
    }

    let config_path_str = unsafe {
        match std::ffi::CStr::from_ptr(config_path).to_str() {
            Ok(s) => s,
            Err(e) => {
                eprintln!("Error: Invalid config path string: {}", e);
                return std::ptr::null_mut();
            }
        }
    };

    match SignalProcessorFFI::new_from_config(config_path_str) {
        Ok(processor_ffi) => {
            let boxed_processor = Box::new(processor_ffi);
            Box::into_raw(boxed_processor) as *mut c_void
        }
        Err(e) => {
            eprintln!("Error creating signal processor from config: {}", e);
            std::ptr::null_mut()
        }
    }
}

// Keep the old function for backward compatibility but mark as deprecated
#[deprecated(note = "Use create_signal_processor_from_config instead")]
#[no_mangle]
pub extern "C" fn create_signal_processor(verbose: bool, fs: f64, channel: usize) -> *mut c_void {
    eprintln!("Warning: create_signal_processor is deprecated. Use create_signal_processor_from_config instead.");

    // For now, create a minimal config and use the new system
    // This is a temporary bridge - users should migrate to config files
    use crate::processing::signal_processor::SignalProcessorConfig;

    let config = SignalProcessorConfig {
        verbose,
        fs,
        channel,
        enable_debug_logging: true,
    };

    // Note: This creates a processor without filters/detectors/triggers
    // Users should migrate to config-based approach for full functionality
    let processor = SignalProcessor::new(config);

    let processor_ffi = SignalProcessorFFI {
        processor,
        context_buffer: VecDeque::with_capacity(4096 + 4000),
        context_size: 2000,
    };

    let boxed_processor = Box::new(processor_ffi);
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

// Keep existing manual configuration functions but mark as deprecated
#[deprecated(note = "Use YAML configuration instead")]
#[no_mangle]
pub extern "C" fn add_filter(
    processor_ptr: *mut c_void,
    id: *const c_char,
    f_low: f64,
    f_high: f64,
    fs: f64,
) {
    eprintln!("Warning: add_filter is deprecated. Use YAML configuration instead.");

    let processor = unsafe { &mut *(processor_ptr as *mut SignalProcessorFFI) };
    let id_str = unsafe { CString::from_raw(id as *mut c_char) }
        .into_string()
        .unwrap();

    use crate::processing::filters::bandpass::{BandPassFilter, BandPassFilterConfig};

    let config = BandPassFilterConfig {
        id: id_str,
        f_low,
        f_high,
    };
    let filter = BandPassFilter::new(config, fs);
    processor.processor.add_filter(Box::new(filter));
}

#[deprecated(note = "Use YAML configuration instead")]
#[no_mangle]
pub extern "C" fn add_wave_peak_detector(
    processor_ptr: *mut c_void,
    id: *const c_char,
    filter_id: *const c_char,
    z_score_threshold: f64,
    sinusoidness_threshold: f64,
    check_sinusoidness: bool,
    wave_polarity: *const c_char,
    min_wave_length_ms: f64,
    max_wave_length_ms: f64,
) {
    eprintln!("Warning: add_wave_peak_detector is deprecated. Use YAML configuration instead.");

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

    use crate::processing::detectors::wave_peak::{WavePeakDetector, WavePeakDetectorConfig};

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

#[deprecated(note = "Use YAML configuration instead")]
#[no_mangle]
pub extern "C" fn add_pulse_trigger(
    processor_ptr: *mut c_void,
    id: *const c_char,
    activation_detector_id: *const c_char,
    inhibition_detector_id: *const c_char,
    inhibition_cooldown_ms: f64,
    pulse_cooldown_ms: f64,
) {
    eprintln!("Warning: add_pulse_trigger is deprecated. Use YAML configuration instead.");

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

    use crate::processing::triggers::pulse::{PulseTrigger, PulseTriggerConfig};

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

    // Strictly maintain buffer size
    let max_buffer_size = length + (processor.context_size * 2);
    while processor.context_buffer.len() > max_buffer_size {
        processor.context_buffer.pop_front();
    }

    // Process the data
    let (_output, trigger_timestamp_option) = processor.processor.run_chunk(Vec::from(data_slice));

    if let Some(trigger_timestamp) = trigger_timestamp_option {
        let result_ptr = Box::into_raw(Box::new(trigger_timestamp));
        return result_ptr as *mut c_void;
    }

    std::ptr::null_mut()
}
