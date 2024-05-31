use crate::processing::signal_processor::SignalProcessorConfig;
use std::collections::HashMap;
use std::time::{Duration, Instant};

use super::TriggerInstance;

pub struct PulseTriggerConfig {
    pub id: String,
    pub activation_detector_id: String,
    pub inhibition_detector_id: String,
    pub inhibition_cooldown_ms: Duration,
    pub pulse_cooldown_ms: Duration,
}

pub struct PulseTrigger {
    config: PulseTriggerConfig,
    last_pulse_time: Option<Instant>,
    last_inhibition_time: Option<Instant>,
}

impl PulseTrigger {
    pub fn new(config: PulseTriggerConfig) -> Self {
        Self {
            config,
            last_pulse_time: None,
            last_inhibition_time: None,
        }
    }
}

impl TriggerInstance for PulseTrigger {
    fn id(&self) -> &str {
        &self.config.id
    }

    fn activation_detector_id(&self) -> String {
        self.config.activation_detector_id.clone()
    }

    fn inhibition_detector_id(&self) -> String {
        self.config.inhibition_detector_id.clone()
    }

    fn evaluate(
        &mut self,
        global_config: &SignalProcessorConfig,
        results: &mut HashMap<String, f64>,
    ) {
        let now = Instant::now();

        // Check if the activation or inhibition cooldowns are active.
        if self.last_inhibition_time.map_or(false, |t| {
            now.duration_since(t) < self.config.inhibition_cooldown_ms
        }) || self.last_pulse_time.map_or(false, |t| {
            now.duration_since(t) < self.config.pulse_cooldown_ms
        }) {
            results.insert(format!("triggers:{}:triggered", self.config.id), 0.0);
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
            results.insert(format!("triggers:{}:triggered", self.config.id), 0.0);
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
            self.last_pulse_time = Some(now);
            results.insert(format!("triggers:{}:triggered", self.config.id), 1.0);
        } else {
            results.insert(format!("triggers:{}:triggered", self.config.id), 0.0);
        }

        // If verbose, add more items to the results HashMap
        if global_config.verbose {
            results.insert(
                format!("triggers:{}:activation_active", self.config.id),
                if activation_active { 1.0 } else { 0.0 },
            );
            results.insert(
                format!("triggers:{}:inhibition_active", self.config.id),
                if inhibition_active { 1.0 } else { 0.0 },
            );
        }
    }
}
