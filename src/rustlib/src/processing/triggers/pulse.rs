use crate::processing::signal_processor::SignalProcessorConfig;
use std::collections::HashMap;

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
    pulse_cooldown_remaining: usize,
    inhibition_cooldown_remaining: usize,
}

impl PulseTrigger {
    pub fn new(config: PulseTriggerConfig) -> Self {
        Self {
            config,
            pulse_cooldown_remaining: 0,
            inhibition_cooldown_remaining: 0,
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
        // let inhibition_cooldown_samples =
        //     self.cooldown_samples(self.config.inhibition_cooldown_ms, global_config.fs);
        // let pulse_cooldown_samples =
        //     self.cooldown_samples(self.config.pulse_cooldown_ms, global_config.fs);

        // Decrement the cooldown counters if they are greater than zero
        if self.inhibition_cooldown_remaining > 0 {
            self.inhibition_cooldown_remaining -= 1;
        }
        if self.pulse_cooldown_remaining > 0 {
            self.pulse_cooldown_remaining -= 1;
        }

        // Determine if the inhibition is active; if so, reset the trigger and set the cooldown
        let inhibition_active = results
            .get(&format!(
                "detectors:{}:detected",
                self.config.inhibition_detector_id
            ))
            .cloned()
            .unwrap_or(0.0)
            > 0.0;

        if inhibition_active {
            self.inhibition_cooldown_remaining =
                self.cooldown_samples(self.config.inhibition_cooldown_ms, global_config.fs);
            results.insert(format!("triggers:{}:triggered", self.config.id), 0.0);
            return;
        }

        // Determine if the activation is active; if so, set the trigger and set the cooldown
        let activation_active = results
            .get(&format!(
                "detectors:{}:detected",
                self.config.activation_detector_id
            ))
            .cloned()
            .unwrap_or(0.0)
            > 0.0;

        if activation_active && self.pulse_cooldown_remaining == 0 {
            self.pulse_cooldown_remaining =
                self.cooldown_samples(self.config.pulse_cooldown_ms, global_config.fs);
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
                self.pulse_cooldown_remaining as f64,
            );
            results.insert(
                format!(
                    "triggers:{}:inhibition_cooldown_samples_remaining",
                    self.config.id
                ),
                self.inhibition_cooldown_remaining as f64,
            );
        }
    }
}
