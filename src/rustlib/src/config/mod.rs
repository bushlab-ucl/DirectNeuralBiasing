// src/rustlib/src/config/mod.rs
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Config {
    pub processor: ProcessorConfig,
    pub filters: FiltersConfig,
    pub detectors: DetectorsConfig,
    pub triggers: TriggersConfig,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ProcessorConfig {
    pub verbose: bool,
    pub fs: f64,
    pub channel: usize,
    pub enable_debug_logging: bool,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FiltersConfig {
    pub bandpass_filters: Vec<BandpassFilterConfig>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct BandpassFilterConfig {
    pub id: String,
    pub f_low: f64,
    pub f_high: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DetectorsConfig {
    pub wave_peak_detectors: Vec<WavePeakDetectorConfig>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct WavePeakDetectorConfig {
    pub id: String,
    pub filter_id: String,
    pub z_score_threshold: f64,
    pub sinusoidness_threshold: f64,
    pub check_sinusoidness: bool,
    pub wave_polarity: String,
    pub min_wave_length_ms: Option<f64>,
    pub max_wave_length_ms: Option<f64>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TriggersConfig {
    pub pulse_triggers: Vec<PulseTriggerConfig>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct PulseTriggerConfig {
    pub id: String,
    pub activation_detector_id: String,
    pub inhibition_detector_id: String,
    pub inhibition_cooldown_ms: f64,
    pub pulse_cooldown_ms: f64,
}

pub fn load_config<P: AsRef<Path>>(path: P) -> Result<Config, String> {
    let config_str = fs::read_to_string(path)
        .map_err(|e| format!("Failed to read config file: {}", e))?;
    
    serde_yaml::from_str(&config_str)
        .map_err(|e| format!("Failed to parse config file: {}", e))
}

pub fn save_config<P: AsRef<Path>>(config: &Config, path: P) -> Result<(), String> {
    let yaml = serde_yaml::to_string(config)
        .map_err(|e| format!("Failed to serialize config: {}", e))?;
    
    fs::write(path, yaml)
        .map_err(|e| format!("Failed to write config file: {}", e))
}