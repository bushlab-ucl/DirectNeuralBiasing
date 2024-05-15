pub mod pulse;

use std::collections::HashMap;

pub trait TriggerInstance: Send {
    fn id(&self) -> &str;
    fn evaluate(&mut self, results: &mut HashMap<String, f64>, trigger_id: &str);
}
