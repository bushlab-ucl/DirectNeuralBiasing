use std::io::{self, Read};
// use std::net::TcpStream;

// use crate::filters::bandpass::BandPassFilter;
// use crate::processing::detectors::threshold_detector::ThresholdDetector;
// use crate::processing::signal_processor::{Config, Controller, SignalProcessor};

// emptry pass
pub fn run() -> io::Result<()> {
    Ok(())
}

// // In client.rs
// pub fn run() -> io::Result<()> {
//     use std::io::{self, Read};
//     use std::net::TcpStream;

//     let mut stream = TcpStream::connect("127.0.0.1:8080")?;
//     let mut buffer = [0u8; 4];

//     let f0 = 100.0;
//     let fs = 10000.0;

//     let butterworth = BandPassFilter::butterworth(f0, fs);

//     // Configure the controller with appropriate settings
//     let config = Config {
//         downsampling_rate: 100,                               // Example setting
//         logging: true,                                        // Logging enabled
//         trigger_cooldown: std::time::Duration::from_secs(10), // 10 seconds trigger cooldown
//         detector_cooldown: std::time::Duration::from_secs(2), // 2 seconds detector cooldown
//     };
//     let mut controller = Controller::new(config);

//     // Adding detectors to the controller
//     let z_score_threshold = 1.0; // z-score threshold
//     let buffer_size = 100; // buffer size for z-scores
//     let sensitivity_1 = 0.1; // sensitivity configuration
//     let sensitivity_2 = 0.8;

//     let test_detector_1 = Box::new(ThresholdDetector::new(
//         "test_1".to_string(),
//         z_score_threshold,
//         buffer_size,
//         sensitivity_1,
//     ));
//     let test_detector_2 = Box::new(ThresholdDetector::new(
//         "test_2".to_string(),
//         z_score_threshold,
//         buffer_size,
//         sensitivity_2,
//     ));

//     // Attach detectors to controller
//     controller.add_active_detector(test_detector_1);
//     controller.add_active_detector(test_detector_2);

//     // Create SignalProcessor with the controller
//     let mut processor = SignalProcessor::new(butterworth, controller);

//     loop {
//         match stream.read_exact(&mut buffer) {
//             Ok(_) => {
//                 let raw = i32::from_be_bytes(buffer).abs() as f64;
//                 let controller_output = processor.process_sample(raw);
//                 if controller_output.trigger_event {
//                     for output in controller_output.detector_outputs {
//                         if output.detected {
//                             println!(
//                                 "{} detected - confidence: {}",
//                                 output.name,
//                                 output.confidence.floor()
//                             );
//                         }
//                     }
//                 }
//             }
//             Err(e) => return Err(e),
//         }
//     }
// }
