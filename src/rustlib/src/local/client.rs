use std::io::{self, Read};
use std::net::TcpStream;

use colored::Colorize;
use std::time::{Duration, Instant};

use crate::processing::detectors::threshold::{ThresholdDetector, ThresholdDetectorConfig};
use crate::processing::detectors::wave_peak::{WavePeakDetector, WavePeakDetectorConfig};
use crate::processing::filters::bandpass::{BandPassFilter, BandPassFilterConfig};
use crate::processing::signal_processor::{SignalProcessor, SignalProcessorConfig};
use crate::processing::triggers::pulse::{PulseTrigger, PulseTriggerConfig};

pub fn run() -> io::Result<()> {
    let mut stream = TcpStream::connect("127.0.0.1:8080")?;
    let mut buffer = [0u8; 4];

    let processor_config = SignalProcessorConfig {
        verbose: true,
        fs: 512.0,
        channel: 1,
    };

    let mut processor = SignalProcessor::new(processor_config);

    let ied_filter_config = BandPassFilterConfig {
        id: "ied_filter".to_string(),
        f_low: 80.0,
        f_high: 120.0,
        fs: 512.0,
    };
    let ied_filter = BandPassFilter::new(ied_filter_config);
    processor.add_filter(Box::new(ied_filter));

    let slow_wave_filter_config = BandPassFilterConfig {
        id: "slow_wave_filter".to_string(),
        f_low: 0.5,
        f_high: 4.0,
        fs: 512.0,
    };
    let slow_wave_filter = BandPassFilter::new(slow_wave_filter_config);
    processor.add_filter(Box::new(slow_wave_filter));

    let ied_detector_config = ThresholdDetectorConfig {
        id: "ied_detector".to_string(),
        filter_id: "ied_filter".to_string(),
        z_score_threshold: 3.0,
        buffer_size: 10,
        sensitivity: 0.5,
    };
    let ied_detector = ThresholdDetector::new(ied_detector_config);
    processor.add_detector(Box::new(ied_detector));

    // let swr_detector_config = ThresholdDetectorConfig {
    //     id: "swr_detector".to_string(),
    //     filter_id: "butterworth".to_string(),
    //     threshold: 3.0,
    //     buffer_size: 100,
    //     sensitivity: 0.2,
    // };
    // let swr_detector = ThresholdDetector::new(swr_detector_config);
    // processor.add_detector(Box::new(swr_detector));

    let slow_wave_detector_config = WavePeakDetectorConfig {
        id: "slow_wave_detector".to_string(),
        filter_id: "slow_wave_filter".to_string(),
        z_score_threshold: 1.0,
        sinusoidness_threshold: 0.5,
        check_sinusoidness: true,
        wave_polarity: "downwave".to_string(),
        min_wave_length_ms: Some(500.0),
        max_wave_length_ms: Some(2000.0),
    };

    let slow_wave_detector = WavePeakDetector::new(slow_wave_detector_config);
    processor.add_detector(Box::new(slow_wave_detector));

    let trigger_config = PulseTriggerConfig {
        id: "main_trigger".to_string(),
        activation_detector_id: "slow_wave_detector".to_string(),
        inhibition_detector_id: "ied_detector".to_string(),
        inhibition_cooldown_ms: 2000.0,
        pulse_cooldown_ms: 2000.0,
    };
    let main_trigger = PulseTrigger::new(trigger_config);
    processor.add_trigger(Box::new(main_trigger));

    let mut total_processing_time = Duration::new(0, 0);
    let mut sample_count = 0;

    while let Ok(_) = stream.read_exact(&mut buffer) {
        let raw_sample = f32::from_be_bytes(buffer).abs() as f64;
        println!("Received sample: {}", raw_sample);

        let start_time = Instant::now();
        let output = processor.run_chunk(vec![raw_sample]);
        let duration = start_time.elapsed();

        total_processing_time += duration;
        sample_count += 1;
        let average_processing_time = total_processing_time / sample_count;

        println!("Processed sample in {:?}", duration);
        println!(
            "Average processing time per sample: {:?}",
            average_processing_time
        );

        if let Some(results) = output.last() {
            println!("Complete Results: {:#?}", results);

            // Display the filtered signal
            if let Some(&filtered_signal) = results.get("filters:butterworth:filtered_signal") {
                println!("Filtered signal: {:.2}", filtered_signal);
            }

            // SWR detector output
            if let Some(&swr_detection) = results.get("detectors:swr_detector:detected") {
                let message = format!("SWR Detector Output: {:.2}", swr_detection);
                if swr_detection > 0.0 {
                    println!("{}", message.green());
                } else {
                    println!("{}", message.red());
                }
            }

            // Slow Wave detector output
            if let Some(&slow_wave_detection) = results.get("detectors:slow_wave_detector:detected")
            {
                let message = format!("Slow Wave Detector Output: {:.2}", slow_wave_detection);
                if slow_wave_detection > 0.0 {
                    println!("{}", message.green());
                } else {
                    println!("{}", message.red());
                }
            }

            // IED detector output
            if let Some(&ied_detection) = results.get("detectors:ied_detector:detected") {
                let message = format!("IED Detector Output: {:.2}", ied_detection);
                if ied_detection > 0.0 {
                    println!("{}", message.green());
                } else {
                    println!("{}", message.red());
                }
            }

            // Trigger result
            if let Some(&triggered) = results.get("triggers:main_trigger:triggered") {
                let message = format!("Trigger Result: {:.2}", triggered);
                if triggered > 0.0 {
                    println!("{}", message.blue());
                } else {
                    println!("{}", message.red());
                }
            }
        }
    }

    Ok(())
}
