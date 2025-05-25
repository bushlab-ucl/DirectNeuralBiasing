use crate::processing::detectors::wave_peak::{WavePeakDetectorConfig};
use crate::processing::filters::bandpass::{BandPassFilterConfig};
use crate::processing::signal_processor::{SignalProcessorConfig};
use crate::processing::triggers::pulse::{PulseTriggerConfig};

use serde::{Deserialize, Serialize};
use std::fs;
use std::path::Path;

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Config {
    pub processor: SignalProcessorConfig,
    pub filters: FiltersConfig,
    pub detectors: DetectorsConfig,
    pub triggers: TriggersConfig,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FiltersConfig {
    pub bandpass_filters: Vec<BandPassFilterConfig>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DetectorsConfig {
    pub wave_peak_detectors: Vec<WavePeakDetectorConfig>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TriggersConfig {
    pub pulse_triggers: Vec<PulseTriggerConfig>,
}

pub fn load_config<P: AsRef<Path>>(path: P) -> Result<Config, String> {
    let config_str = fs::read_to_string(path)
        .map_err(|e| format!("Failed to read config file: {}", e))?;
    
    serde_yaml::from_str(&config_str)
        .map_err(|e| format!("Failed to parse config file: {}", e))
}