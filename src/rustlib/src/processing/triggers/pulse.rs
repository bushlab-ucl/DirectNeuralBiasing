use std::collections::HashMap;
use std::time::{Duration, Instant};

use super::TriggerInstance;

pub struct PulseTriggerConfig {
    pub trigger_id: String,
    pub activation_detector_id: String,
    pub inhibition_detector_id: String,
    pub activation_cooldown: Duration,
    pub inhibition_cooldown: Duration,
}

pub struct PulseTrigger {
    config: PulseTriggerConfig,
    last_activation_time: Option<Instant>,
    last_inhibition_time: Option<Instant>,
}

impl PulseTrigger {
    pub fn new(config: PulseTriggerConfig) -> Self {
        Self {
            config,
            last_activation_time: None,
            last_inhibition_time: None,
        }
    }
}

impl TriggerInstance for PulseTrigger {
    fn evaluate(&mut self, results: &mut HashMap<String, f64>, trigger_id: &str) {
        let now = Instant::now();

        // Check if the activation or inhibition cooldowns are active.
        if self.last_inhibition_time.map_or(false, |t| {
            now.duration_since(t) < self.config.inhibition_cooldown
        }) || self.last_activation_time.map_or(false, |t| {
            now.duration_since(t) < self.config.activation_cooldown
        }) {
            results.insert(format!("triggers:{}:triggered", trigger_id), 0.0);
            return;
        }

        // Determine if the inhibition is active; if so, reset the trigger.
        let inhibition_active = results
            .get(&format!(
                "detectors:{}:detected",
                self.config.inhibition_detector_id
            ))
            .cloned()
            .unwrap_or(0.0)
            > 0.0;

        if inhibition_active {
            self.last_inhibition_time = Some(now);
            results.insert(format!("triggers:{}:triggered", trigger_id), 0.0);
            return;
        }

        // Determine if the activation is active; if so, set the trigger.
        let activation_active = results
            .get(&format!(
                "detectors:{}:detected",
                self.config.activation_detector_id
            ))
            .cloned()
            .unwrap_or(0.0)
            > 0.0;

        if activation_active {
            self.last_activation_time = Some(now);
            results.insert(format!("triggers:{}:triggered", trigger_id), 1.0);
        } else {
            results.insert(format!("triggers:{}:triggered", trigger_id), 0.0);
        }
    }
}
