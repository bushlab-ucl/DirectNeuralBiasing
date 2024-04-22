use std::io::{self, Read};
use std::net::TcpStream;

use crate::filters::bandpass::BandPassFilter;
use crate::processing::detectors::threshold_detector::ThresholdDetector;
use crate::processing::signal_processor::{Config, SignalProcessor};

// In client.rs
pub fn run() -> io::Result<()> {
    let mut stream = TcpStream::connect("127.0.0.1:8080")?;
    let mut buffer = [0u8; 4];

    let f0 = 100.0;
    let fs = 10000.0;

    let butterworth = BandPassFilter::butterworth(f0, fs);
    let mut processor = SignalProcessor::new(butterworth, Config::new(false));

    let test_detector_1 = Box::new(ThresholdDetector::new("test_1".to_string(), 1.0, 100, 10));
    let test_detector_2 = Box::new(ThresholdDetector::new("test_2".to_string(), 1.0, 100, 80));
    processor.add_detector(test_detector_1);
    processor.add_detector(test_detector_2);

    loop {
        match stream.read_exact(&mut buffer) {
            Ok(_) => {
                let raw = i32::from_be_bytes(buffer).abs() as f64;
                // println!("{}", processor.index);
                let detections = processor.process_sample(raw);
                if !detections.is_empty() {
                    for detection in detections {
                        println!(
                            "{} detected - confidence: {}",
                            detection.name,
                            detection.confidence.floor()
                        );
                    }
                }
            }
            Err(e) => return Err(e),
        }
    }
}
