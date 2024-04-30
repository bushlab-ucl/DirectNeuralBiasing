use super::detectors::DetectorInstance;
use std::collections::HashMap;
pub mod pulse_trigger;

pub trait TriggerInstance: Send {
    fn evaluate(&mut self, detectors: &HashMap<String, Box<dyn DetectorInstance>>) -> bool;
    fn trigger_id(&self) -> String;
}
