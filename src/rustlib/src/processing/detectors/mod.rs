pub mod slow_wave;
use rayon::prelude::*;

// DETECTOR COMPONENT ----------------------------------------------------------
pub trait DetectorInstance {
    fn process_sample(
        &mut self,
        sample: f64,
        index: usize,
        prev_sample: f64,
        mean: f64,
        std_dev: f64,
    ) -> Option<Vec<usize>>;
}

// Buffer COMPONENT ------------------------------------------------------------

struct RingBuffer {
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

    pub fn add(&mut self, sample: f64) {
        self.buffer[self.end] = sample;
        self.end = (self.end + 1) % self.capacity;
        if self.end == self.start {
            self.start = (self.start + 1) % self.capacity; // Overwrite oldest if full
        }
    }

    pub fn get(&self, index: usize) -> Option<f64> {
        if index >= self.capacity {
            return None;
        }
        let adjusted_index = (self.start + index) % self.capacity;
        Some(self.buffer[adjusted_index])
    }
}
