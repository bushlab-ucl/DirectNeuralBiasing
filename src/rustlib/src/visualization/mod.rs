// src/rustlib/src/visualization/mod.rs

pub mod plotter;
pub mod window;

use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct VisualizationConfig {
    pub enabled: bool,
    pub window_width: u32,
    pub window_height: u32,
    pub buffer_size: usize,
    pub update_interval_ms: u64,
    pub show_raw_signal: bool,
    pub show_filtered_signals: bool,
    pub show_detections: bool,
    pub plot_height_per_signal: u32,
}

impl Default for VisualizationConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            window_width: 1200,
            window_height: 800,
            buffer_size: 5000,
            update_interval_ms: 16, // ~60 FPS
            show_raw_signal: true,
            show_filtered_signals: true,
            show_detections: true,
            plot_height_per_signal: 150,
        }
    }
}

pub struct VisualizationData {
    pub timestamp: f64,
    pub raw_sample: f64,
    pub filtered_samples: Vec<(String, f64)>, // (filter_id, value)
    pub detections: Vec<(String, bool)>,      // (detector_id, detected)
}
