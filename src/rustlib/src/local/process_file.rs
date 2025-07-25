use std::collections::VecDeque;
use std::fs::File;
use std::io::{self, BufRead, BufReader};
use std::path::Path;
use std::time::Instant;

use crate::processing::signal_processor::SignalProcessor;

// use crate::processing::detectors::threshold::{ThresholdDetector, ThresholdDetectorConfig};
// use crate::processing::detectors::wave_peak::{WavePeakDetector, WavePeakDetectorConfig};
// use crate::processing::filters::bandpass::{BandPassFilter, BandPassFilterConfig};
// use crate::processing::signal_processor::{SignalProcessor, SignalProcessorConfig};
// use crate::processing::triggers::pulse::{PulseTrigger, PulseTriggerConfig};

fn count_lines<P>(filename: P) -> io::Result<usize>
where
    P: AsRef<Path>,
{
    let file = File::open(filename)?;
    let reader = BufReader::new(file);
    let mut count = 0;
    for line in reader.lines() {
        if line.is_ok() {
            count += 1;
        }
    }
    Ok(count)
}

pub fn run() -> io::Result<()> {
    let data_file_path = "./data/test_waveform.csv";
    let config_file_path = "./config/config.yaml";

    if !Path::new(data_file_path).exists() {
        eprintln!("Error: Data file not found at path: {}", data_file_path);
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            "Data file not found",
        ));
    }

    if !Path::new(config_file_path).exists() {
        eprintln!("Error: Config file not found at path: {}", config_file_path);
        return Err(io::Error::new(
            io::ErrorKind::NotFound,
            "Config file not found",
        ));
    }

    // Initialize signal processor from config file
    let mut processor = match SignalProcessor::from_config_file(config_file_path) {
        Ok(p) => p,
        Err(e) => {
            eprintln!("Error initializing signal processor from config: {}", e);
            return Err(io::Error::new(io::ErrorKind::Other, e));
        }
    };

    let chunk_size = 4096;
    let context_size = 2000;
    let max_buffer_size = chunk_size + (context_size * 2);
    let mut samples = Vec::with_capacity(chunk_size);
    let mut counter = 0;
    let mut global_counter = 0;
    let mut sample_buffer = VecDeque::with_capacity(max_buffer_size);
    let mut chunk_count = 0; // Count the number of chunks processed
                             // let mut detected_events = 0; // Count the number of detected events

    // let mut output_file = File::create("output.csv")?;

    let total_lines = count_lines(data_file_path)?;
    let total_chunks = (total_lines + chunk_size - 1) / chunk_size;

    let file = File::open(data_file_path)?;
    let reader = BufReader::new(file);

    for line in reader.lines() {
        let line = line?;
        let sample: f64 = line.parse().unwrap_or(0.0);

        samples.push(sample);
        counter += 1;
        global_counter += 1;

        if counter >= chunk_size {
            // Reset the counter and process the chunk
            counter = 0;
            chunk_count += 1;

            let start_time = Instant::now(); // Start timer before analysis
            let (output, _timestamp) = processor.run_chunk(samples.clone());
            let duration = start_time.elapsed();

            println!(
                "Processed chunk {:?} / {:?} in {:?} - index: {:?}",
                chunk_count, total_chunks, duration, global_counter
            );

            // Add new data to sample buffer
            sample_buffer.extend(output);

            // Strictly maintain buffer size
            while sample_buffer.len() > max_buffer_size {
                sample_buffer.pop_front(); // Remove oldest samples
            }

            // // Check if the sample in the middle of the buffer is an event
            // let middle_sample = sample_buffer.get(context_size).unwrap();

            // // If the middle sample is an event, write the context to the file
            // if let Some(&triggered) = middle_sample.get("triggers:pulse_trigger:triggered") {
            //     if triggered == 1.0 {
            //         detected_events += 1;
            //         println!("Detected event: {:?}", middle_sample);

            //         println!(
            //             "Writing to file: Detected event {} - chunk {}/{}",
            //             detected_events, chunk_count, total_chunks
            //         );

            //         for results in &sample_buffer {
            //             writeln!(output_file, "{:?}", results)?;
            //         }

            //         println!("Finished writing event to file");
            //     }
            // }

            // Clean and reset for next chunk
            samples.clear();
        }
    }

    Ok(())
}

// PRE CONFIG-FILE
// pub fn run() -> io::Result<()> {
//     let data_file_path = "./data/test_waveform.csv";
//     if !Path::new(data_file_path).exists() {
//         eprintln!("Error: Data file not found at path: {}", data_file_path);
//         return Err(io::Error::new(
//             io::ErrorKind::NotFound,
//             "Data file not found",
//         ));
//     }

//     let chunk_size = 4096;
//     let context_size = 2000;
//     let max_buffer_size = chunk_size + (context_size * 2);
//     let mut samples = Vec::with_capacity(chunk_size);
//     let mut counter = 0;
//     let mut global_counter = 0;
//     let mut sample_buffer = VecDeque::with_capacity(max_buffer_size);
//     let mut chunk_count = 0; // Count the number of chunks processed
//     let mut detected_events = 0; // Count the number of detected events

//     let mut output_file = File::create("output.csv")?;

//     let total_lines = count_lines(data_file_path)?;
//     let total_chunks = (total_lines + chunk_size - 1) / chunk_size;

//     let file = File::open(data_file_path)?;
//     let reader = BufReader::new(file);

//     let processor_config = SignalProcessorConfig {
//         verbose: true,
//         fs: 512.0,
//         channel: 1,
//         enable_debug_logging: true, // Enable logging for now
//     };

//     let mut processor = SignalProcessor::new(processor_config);

//     let ied_filter_config = BandPassFilterConfig {
//         id: "ied_filter".to_string(),
//         f_low: 80.0,
//         f_high: 120.0,
//         fs: 512.0,
//     };
//     let ied_filter = BandPassFilter::new(ied_filter_config);
//     processor.add_filter(Box::new(ied_filter));

//     let slow_wave_filter_config = BandPassFilterConfig {
//         id: "slow_wave_filter".to_string(),
//         f_low: 0.5,
//         f_high: 4.0,
//         fs: 512.0,
//     };
//     let slow_wave_filter = BandPassFilter::new(slow_wave_filter_config);
//     processor.add_filter(Box::new(slow_wave_filter));

//     let ied_detector_config = ThresholdDetectorConfig {
//         id: "ied_detector".to_string(),
//         filter_id: "ied_filter".to_string(),
//         z_score_threshold: 2.0,
//         buffer_size: 10,
//         sensitivity: 0.5,
//     };
//     let ied_detector = ThresholdDetector::new(ied_detector_config);
//     processor.add_detector(Box::new(ied_detector));

//     let slow_wave_detector_config = WavePeakDetectorConfig {
//         id: "slow_wave_detector".to_string(),
//         filter_id: "slow_wave_filter".to_string(),
//         z_score_threshold: 2.0,
//         sinusoidness_threshold: 0.6,
//         check_sinusoidness: false,
//         wave_polarity: "downwave".to_string(),
//         min_wave_length_ms: Some(500.0),
//         max_wave_length_ms: Some(2000.0),
//     };

//     let slow_wave_detector = WavePeakDetector::new(slow_wave_detector_config);
//     processor.add_detector(Box::new(slow_wave_detector));

//     let trigger_config = PulseTriggerConfig {
//         id: "pulse_trigger".to_string(),
//         activation_detector_id: "slow_wave_detector".to_string(),
//         inhibition_detector_id: "ied_detector".to_string(),
//         inhibition_cooldown_ms: 1000.0,
//         pulse_cooldown_ms: 0.0,
//     };
//     let main_trigger = PulseTrigger::new(trigger_config);
//     processor.add_trigger(Box::new(main_trigger));

//     for line in reader.lines() {
//         let line = line?;
//         let sample: f64 = line.parse().unwrap_or(0.0);

//         samples.push(sample);
//         counter += 1;
//         global_counter += 1;

//         if counter >= chunk_size {
//             // Reset the counter and process the chunk
//             counter = 0;
//             chunk_count += 1;

//             let start_time = Instant::now(); // Start timer before analysis
//             let (output, _timestamp) = processor.run_chunk(samples.clone());
//             let duration = start_time.elapsed();

//             println!(
//                 "Processed chunk {:?} / {:?} in {:?} - index: {:?}",
//                 chunk_count, total_chunks, duration, global_counter
//             );

//             // Add new data to sample buffer
//             sample_buffer.extend(output);

//             // Strictly maintain buffer size
//             while sample_buffer.len() > max_buffer_size {
//                 sample_buffer.pop_front();  // Remove oldest samples
//             }

//             // Check if the sample in the middle of the buffer is an event
//             let middle_sample = sample_buffer.get(context_size).unwrap();

//             // If the middle sample is an event, write the context to the file
//             if let Some(&triggered) = middle_sample.get("triggers:pulse_trigger:triggered")
//             {
//                 if triggered == 1.0 {
//                     detected_events += 1;
//                     println!("Detected event: {:?}", middle_sample);

//                     println!(
//                         "Writing to file: Detected event {} - chunk {}/{}",
//                         detected_events, chunk_count, total_chunks
//                     );

//                     for results in &sample_buffer {
//                         writeln!(output_file, "{:?}", results)?;
//                     }

//                     println!("Finished writing event to file");
//                 }
//             }

//             // Clean and reset for next chunk
//             samples.clear();
//         }
//     }

//     Ok(())
// }
