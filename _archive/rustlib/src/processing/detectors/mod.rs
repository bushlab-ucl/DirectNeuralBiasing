// TMP REMOVE THRESHOLD MODULE TO STOP WARNINGS
// pub mod threshold; 
pub mod wave_peak;

use crate::processing::signal_processor::SignalProcessorConfig;
use std::collections::HashMap;

pub trait DetectorInstance: Send {
    fn id(&self) -> &str;
    fn filter_id(&self) -> String;
    fn process_sample(
        &mut self,
        global_config: &SignalProcessorConfig,
        results: &mut HashMap<&'static str, f64>,
        index: usize,
    );
}

// // BUFFER COMPONENT ------------------------------------------------------------

// #[derive(Clone)]
// pub struct RingBuffer {
//     buffer: Vec<f64>,
//     capacity: usize,
//     start: usize,
//     end: usize,
// }

// impl RingBuffer {
//     pub fn new(capacity: usize) -> Self {
//         Self {
//             buffer: vec![0.0; capacity],
//             capacity,
//             start: 0,
//             end: 0,
//         }
//     }

//     pub fn add(&mut self, element: f64) {
//         self.buffer[self.end] = element;
//         self.end = (self.end + 1) % self.capacity;
//         if self.end == self.start {
//             self.start = (self.start + 1) % self.capacity; // Overwrite oldest if full
//         }
//     }

//     #[allow(dead_code)]
//     pub fn get(&self, index: usize) -> Option<f64> {
//         if index >= self.capacity {
//             return None;
//         }
//         let adjusted_index = (self.start + index) % self.capacity;
//         Some(self.buffer[adjusted_index])
//     }
// }

// STATISTICS COMPONENT --------------------------------------------------------

#[derive(Clone)]
struct Statistics {
    sum: f64,
    sum_of_squares: f64,
    count: usize,
    mean: f64,
    std_dev: f64,
    z_score: f64,
}

impl Statistics {
    fn new() -> Self {
        Self {
            sum: 0.0,
            sum_of_squares: 0.0,
            count: 0,
            mean: 0.0,
            std_dev: 0.0,
            z_score: 0.0,
        }
    }

    fn update_statistics(&mut self, sample: f64) {
        self.sum += sample;
        self.sum_of_squares += sample * sample;
        self.count += 1;
        self.mean = self.sum / self.count as f64;

        if self.count > 1 {
            let mean_of_squares = self.sum_of_squares / self.count as f64;
            let square_of_mean = self.mean * self.mean;
            let variance = mean_of_squares - square_of_mean;
            self.std_dev = variance.sqrt();

            if self.std_dev != 0.0 {
                self.z_score = (sample - self.mean) / self.std_dev;
            } else {
                self.z_score = 0.0;
            }
        } else {
            self.std_dev = 0.0;
            self.z_score = 0.0;
        }
    }
}
