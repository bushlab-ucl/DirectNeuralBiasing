pub mod bandpass;

use std::collections::HashMap;

// FILTER INSTANCE -------------------------------------------------------------

pub trait FilterInstance: Send {
    // Process the sample using results HashMap
    fn process_sample(&mut self, results: &mut HashMap<String, f64>, filter_id: &str);
}

// STATISTICS COMPONENT --------------------------------------------------------

pub struct Statistics {
    pub sum: f64,
    pub count: usize,
    pub mean: f64,
    pub std_dev: f64,
    pub z_score: f64,
}

impl Statistics {
    fn new() -> Self {
        Self {
            sum: 0.0,
            count: 0,
            mean: 0.0,
            std_dev: 0.0,
            z_score: 0.0,
        }
    }

    fn update_statistics(&mut self, sample: f64) {
        self.sum += sample;
        self.count += 1;
        self.mean = self.sum / self.count as f64;
        // Update standard deviation calculation to correctly reflect population/std sample deviation as needed
        self.std_dev = ((self.sum / self.count as f64) - self.mean.powi(2)).sqrt();
        self.z_score = (sample - self.mean) / self.std_dev;
    }
}
