// pub mod slow_wave;
pub mod threshold_detector;
use super::filters::FilterInstance;
use std::collections::HashMap;
// use rayon::prelude::*;

// DETECTOR COMPONENT ----------------------------------------------------------
pub trait DetectorInstance: Send {
    fn process_sample(
        &mut self,
        filters: &HashMap<String, Box<dyn FilterInstance>>,
        // sample: f64,
        index: usize,
        z_score: f64,
    ) -> Option<DetectionResult>;

    fn filter_id(&self) -> String;
}

pub struct DetectionResult {
    pub name: String,
    pub confidence: f64, // 0 - 100
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
