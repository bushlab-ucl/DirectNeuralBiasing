pub mod bandpass;

use std::collections::HashMap;

// FILTER INSTANCE -------------------------------------------------------------

pub trait FilterInstance: Send {
    // Process the sample using results HashMap
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, filter_id: &str);
}
