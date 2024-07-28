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

pub struct Keys {
    triggered: &'static str,
    activation_active: &'static str,
    inhibition_active: &'static str,
    activation_cooldown_samples_remaining: &'static str,
    inhibition_cooldown_samples_remaining: &'static str,
    activation_detector: &'static str,
    inhibition_detector: &'static str,
}

pub struct PulseTrigger {
    config: PulseTriggerConfig,
    pulse_cooldown_remaining: usize,
    inhibition_cooldown_remaining: usize,
    keys: Keys,
}

impl PulseTrigger {
    pub fn new(config: PulseTriggerConfig) -> Self {
        let keys = Keys {
            triggered: Box::leak(format!("triggers:{}:triggered", config.id).into_boxed_str()),
            activation_active: Box::leak(
                format!("triggers:{}:activation_active", config.id).into_boxed_str(),
            ),
            inhibition_active: Box::leak(
                format!("triggers:{}:inhibition_active", config.id).into_boxed_str(),
            ),
            activation_cooldown_samples_remaining: Box::leak(
                format!(
                    "triggers:{}:activation_cooldown_samples_remaining",
                    config.id
                )
                .into_boxed_str(),
            ),
            inhibition_cooldown_samples_remaining: Box::leak(
                format!(
                    "triggers:{}:inhibition_cooldown_samples_remaining",
                    config.id
                )
                .into_boxed_str(),
            ),
            activation_detector: Box::leak(
                format!("detectors:{}:detected", config.activation_detector_id).into_boxed_str(),
            ),
            inhibition_detector: Box::leak(
                format!("detectors:{}:detected", config.inhibition_detector_id).into_boxed_str(),
            ),
        };

        Self {
            config,
            pulse_cooldown_remaining: 0,
            inhibition_cooldown_remaining: 0,
            keys,
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
        results: &mut HashMap<&'static str, f64>,
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
            .get(self.keys.inhibition_detector)
            .cloned()
            .unwrap_or(0.0)
            > 0.0;

        if inhibition_active {
            self.inhibition_cooldown_remaining =
                self.cooldown_samples(self.config.inhibition_cooldown_ms, global_config.fs);
            results.insert(self.keys.triggered, 0.0);
            return;
        }

        // Determine if the activation is active; if so, set the trigger and set the cooldown
        let activation_active = results
            .get(self.keys.activation_detector)
            .cloned()
            .unwrap_or(0.0)
            > 0.0;

        if activation_active && self.pulse_cooldown_remaining == 0 {
            self.pulse_cooldown_remaining =
                self.cooldown_samples(self.config.pulse_cooldown_ms, global_config.fs);
            results.insert(self.keys.triggered, 1.0);
        } else {
            results.insert(self.keys.triggered, 0.0);
        }

        // If verbose, add more items to the results HashMap
        if global_config.verbose {
            results.insert(
                self.keys.activation_active,
                if activation_active { 1.0 } else { 0.0 },
            );
            results.insert(
                self.keys.inhibition_active,
                if inhibition_active { 1.0 } else { 0.0 },
            );
            results.insert(
                self.keys.activation_cooldown_samples_remaining,
                self.pulse_cooldown_remaining as f64,
            );
            results.insert(
                self.keys.inhibition_cooldown_samples_remaining,
                self.inhibition_cooldown_remaining as f64,
            );
        }
    }
}
