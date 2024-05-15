pub mod bandpass;

use std::collections::HashMap;

pub trait FilterInstance: Send {
    fn id(&self) -> &str;
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, filter_id: &str);
}
