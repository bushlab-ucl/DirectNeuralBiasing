// pub mod slow_wave;
pub mod threshold;

use std::collections::HashMap;

pub trait DetectorInstance: Send {
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
