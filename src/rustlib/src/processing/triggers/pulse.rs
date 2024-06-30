use crate::processing::signal_processor::SignalProcessorConfig;
use std::collections::HashMap;
// use std::time::{Duration, Instant};

use super::TriggerInstance;

pub struct PulseTriggerConfig {
    pub id: String,
    pub activation_detector_id: String,
    pub inhibition_detector_id: String,
    pub inhibition_cooldown_ms: f64,
    pub pulse_cooldown_ms: f64,
}

pub struct PulseTrigger {
    config: PulseTriggerConfig,
    last_pulse_sample: Option<usize>,
    last_inhibition_sample: Option<usize>,
}

impl PulseTrigger {
    pub fn new(config: PulseTriggerConfig) -> Self {
        Self {
            config,
            last_pulse_sample: None,
            last_inhibition_sample: None,
        }
    }

    fn cooldown_samples(&self, cooldown_ms: f64, fs: f64) -> usize {
        ((cooldown_ms / 1000.0) * fs) as usize
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
        let current_sample = results.get("global:index").cloned().unwrap_or(0.0) as usize;
        let inhibition_cooldown_samples =
            self.cooldown_samples(self.config.inhibition_cooldown_ms, global_config.fs);
        let pulse_cooldown_samples =
            self.cooldown_samples(self.config.pulse_cooldown_ms, global_config.fs);

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
            self.last_inhibition_sample = Some(current_sample);
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
            self.last_pulse_sample = Some(current_sample);
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
            results.insert(
                format!(
                    "triggers:{}:activation_cooldown_samples_remaining",
                    self.config.id
                ),
                if let Some(last_pulse_sample) = self.last_pulse_sample {
                    (last_pulse_sample + pulse_cooldown_samples) as f64 - current_sample as f64
                } else {
                    0.0
                },
            );
            results.insert(
                format!(
                    "triggers:{}:inhibition_cooldown_samples_remaining",
                    self.config.id
                ),
                if let Some(last_inhibition_sample) = self.last_inhibition_sample {
                    (last_inhibition_sample + inhibition_cooldown_samples) as f64
                        - current_sample as f64
                } else {
                    0.0
                },
            );
        }
    }
}
