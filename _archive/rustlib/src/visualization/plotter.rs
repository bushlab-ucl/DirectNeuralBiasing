// src/rustlib/src/visualization/plotter.rs

use super::{VisualizationConfig, VisualizationData};
use std::collections::{HashMap, VecDeque};
use std::sync::{Arc, Mutex};

pub struct SignalPlotter {
    config: VisualizationConfig,
    raw_buffer: VecDeque<(f64, f64)>, // (timestamp, value)
    filtered_buffers: HashMap<String, VecDeque<(f64, f64)>>,
    detection_markers: VecDeque<(f64, String, bool)>, // (timestamp, detector_id, active)
}

impl SignalPlotter {
    pub fn new(config: VisualizationConfig) -> Self {
        Self {
            config: config.clone(),
            raw_buffer: VecDeque::with_capacity(config.buffer_size),
            filtered_buffers: HashMap::new(),
            detection_markers: VecDeque::with_capacity(config.buffer_size),
        }
    }

    pub fn add_data(&mut self, data: VisualizationData) {
        // Add raw signal data
        if self.config.show_raw_signal {
            self.raw_buffer.push_back((data.timestamp, data.raw_sample));
            if self.raw_buffer.len() > self.config.buffer_size {
                self.raw_buffer.pop_front();
            }
        }

        // Add filtered signal data
        if self.config.show_filtered_signals {
            for (filter_id, value) in data.filtered_samples {
                let buffer = self
                    .filtered_buffers
                    .entry(filter_id)
                    .or_insert_with(|| VecDeque::with_capacity(self.config.buffer_size));

                buffer.push_back((data.timestamp, value));
                if buffer.len() > self.config.buffer_size {
                    buffer.pop_front();
                }
            }
        }

        // Add detection markers
        if self.config.show_detections {
            for (detector_id, detected) in data.detections {
                if detected {
                    self.detection_markers
                        .push_back((data.timestamp, detector_id, detected));
                    if self.detection_markers.len() > self.config.buffer_size {
                        self.detection_markers.pop_front();
                    }
                }
            }
        }
    }

    pub fn get_raw_buffer(&self) -> Vec<(f64, f64)> {
        self.raw_buffer.iter().copied().collect()
    }

    pub fn get_filtered_buffer(&self, filter_id: &str) -> Option<Vec<(f64, f64)>> {
        self.filtered_buffers
            .get(filter_id)
            .map(|buf| buf.iter().copied().collect())
    }

    pub fn get_all_filtered_buffers(&self) -> HashMap<String, Vec<(f64, f64)>> {
        self.filtered_buffers
            .iter()
            .map(|(id, buf)| (id.clone(), buf.iter().copied().collect()))
            .collect()
    }

    pub fn get_detection_markers(&self) -> Vec<(f64, String, bool)> {
        self.detection_markers.iter().cloned().collect()
    }

    pub fn get_time_range(&self) -> Option<(f64, f64)> {
        if self.raw_buffer.is_empty() {
            return None;
        }

        let min_time = self.raw_buffer.front().map(|(t, _)| *t)?;
        let max_time = self.raw_buffer.back().map(|(t, _)| *t)?;
        Some((min_time, max_time))
    }

    pub fn clear(&mut self) {
        self.raw_buffer.clear();
        self.filtered_buffers.clear();
        self.detection_markers.clear();
    }
}

pub type SharedPlotter = Arc<Mutex<SignalPlotter>>;

pub fn create_shared_plotter(config: VisualizationConfig) -> SharedPlotter {
    Arc::new(Mutex::new(SignalPlotter::new(config)))
}
