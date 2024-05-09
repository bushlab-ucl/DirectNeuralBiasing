use std::io::{self, Read};
use std::net::TcpStream;
use std::time::{Duration, Instant};

use colored::Colorize; // Ensure the 'colored' crate is included in your dependencies

use crate::processing::detectors::threshold::{ThresholdDetector, ThresholdDetectorConfig};
use crate::processing::filters::bandpass::{BandPassFilter, BandPassFilterConfig};
use crate::processing::signal_processor::{SignalProcessor, SignalProcessorConfig};
use crate::processing::triggers::pulse::{PulseTrigger, PulseTriggerConfig};

pub fn run() -> io::Result<()> {
    let mut stream = TcpStream::connect("127.0.0.1:8080")?;
    let mut buffer = [0u8; 4];

    let processor_config = SignalProcessorConfig {
        logging: true,
        downsampling_rate: 1,
    };

    let mut processor = SignalProcessor::new(processor_config);

    let filter_config = BandPassFilterConfig {
        f0: 100.0,
        fs: 10000.0,
    };
    let butterworth_filter = BandPassFilter::new(filter_config);
    processor.add_filter("butterworth".to_string(), Box::new(butterworth_filter));

    let swr_detector_config = ThresholdDetectorConfig {
        filter_id: "butterworth".to_string(),
        threshold: 3.0,
        buffer_size: 100,
        sensitivity: 0.2,
    };
    let swr_detector = ThresholdDetector::new(swr_detector_config);
    processor.add_detector("swr_detector".to_string(), Box::new(swr_detector));

    let ied_detector_config = ThresholdDetectorConfig {
        filter_id: "butterworth".to_string(),
        threshold: 5.0,
        buffer_size: 100,
        sensitivity: 0.2,
    };
    let ied_detector = ThresholdDetector::new(ied_detector_config);
    processor.add_detector("ied_detector".to_string(), Box::new(ied_detector));

    let trigger_config = PulseTriggerConfig {
        trigger_id: "main_trigger".to_string(),
        activation_detector_id: "swr_detector".to_string(),
        inhibition_detector_id: "ied_detector".to_string(),
        activation_cooldown: Duration::from_secs(2),
        inhibition_cooldown: Duration::from_secs(1),
    };
    let main_trigger = PulseTrigger::new(trigger_config);
    processor.add_trigger("main_trigger".to_string(), Box::new(main_trigger));

    while let Ok(_) = stream.read_exact(&mut buffer) {
        let raw_sample = i32::from_be_bytes(buffer).abs() as f64;

        let start_time = Instant::now(); // Start timer before analysis
        let output = processor.run(vec![raw_sample]);
        let duration = start_time.elapsed();

        println!("Processed sample in {:?}", duration); // Timing the analysis phase only

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
                    println!("{}", message.blue()); // Keeping trigger blue for activation
                } else {
                    println!("{}", message.red()); // Red to indicate no trigger
                }
            }
        }
    }

    Ok(())
}
