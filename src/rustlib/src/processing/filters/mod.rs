pub mod bandpass;

pub trait FilterInstance: Send {
    fn filter_sample(&mut self, sample: f64) -> f64;
    fn filter_id(&self) -> String;
}
