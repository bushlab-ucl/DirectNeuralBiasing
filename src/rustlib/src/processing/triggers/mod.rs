use std::collections::HashMap;
pub mod pulse_trigger;

pub trait TriggerInstance: Send {
    fn evaluate(&mut self, results: &mut HashMap<String, f64>, trigger_id: &str);
}
