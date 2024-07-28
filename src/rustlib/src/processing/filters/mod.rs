pub mod bandpass;
use crate::processing::signal_processor::SignalProcessorConfig;
use std::collections::HashMap;

pub trait FilterInstance: Send {
    fn id(&self) -> &str;
    fn process_sample(
        &mut self,
        global_config: &SignalProcessorConfig,
        results: &mut HashMap<&'static str, f64>,
    );
}
