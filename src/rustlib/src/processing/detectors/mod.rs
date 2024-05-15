// pub mod slow_wave;
pub mod slow_wave;
pub mod threshold;

use std::collections::HashMap;

pub trait DetectorInstance: Send {
    fn id(&self) -> &str;
    fn process_sample(
        &mut self,
        results: &mut HashMap<String, f64>,
        index: usize,
        detector_id: &str,
    );
}

// BUFFER COMPONENT ------------------------------------------------------------

#[derive(Clone)]
pub struct RingBuffer {
    buffer: Vec<f64>,
    capacity: usize,
    start: usize,
    end: usize,
}

impl RingBuffer {
    pub fn new(capacity: usize) -> Self {
        Self {
            buffer: vec![0.0; capacity],
            capacity,
            start: 0,
            end: 0,
        }
    }

    pub fn add(&mut self, element: f64) {
        self.buffer[self.end] = element;
        self.end = (self.end + 1) % self.capacity;
        if self.end == self.start {
            self.start = (self.start + 1) % self.capacity; // Overwrite oldest if full
        }
    }

    #[allow(dead_code)]
    pub fn get(&self, index: usize) -> Option<f64> {
        if index >= self.capacity {
            return None;
        }
        let adjusted_index = (self.start + index) % self.capacity;
        Some(self.buffer[adjusted_index])
    }
}

// STATISTICS COMPONENT --------------------------------------------------------

#[derive(Clone)]
pub struct Statistics {
    pub sum: f64,
    pub count: usize,
    pub mean: f64,
    pub std_dev: f64,
    pub z_score: f64,
}

impl Statistics {
    fn new() -> Self {
        Self {
            sum: 0.0,
            count: 0,
            mean: 0.0,
            std_dev: 0.0,
            z_score: 0.0,
        }
    }

    fn update_statistics(&mut self, sample: f64) {
        self.sum += sample;
        self.count += 1;
        self.mean = self.sum / self.count as f64;
        // Update standard deviation calculation to correctly reflect population/std sample deviation as needed
        self.std_dev = ((self.sum / self.count as f64) - self.mean.powi(2)).sqrt();
        self.z_score = (sample - self.mean) / self.std_dev;
    }
}
