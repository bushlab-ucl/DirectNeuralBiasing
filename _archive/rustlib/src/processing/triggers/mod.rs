use crate::processing::signal_processor::SignalProcessorConfig;
use std::collections::HashMap;
pub mod pulse;

pub trait TriggerInstance: Send {
    fn id(&self) -> &str;
    fn activation_detector_id(&self) -> String;
    fn inhibition_detector_id(&self) -> String;
    fn evaluate(
        &mut self,
        global_config: &SignalProcessorConfig,
        results: &mut HashMap<&'static str, f64>,
    );
}
