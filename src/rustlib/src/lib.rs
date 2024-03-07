// use crate::processing::process_signal::PyFilter;
// use pyo3::prelude::*;

pub mod filters;
pub mod processing;
pub mod utils;

// #[pymodule]
// #[pyo3(name = "direct_neural_biasing")]
// fn direct_neural_biasing(_py: Python, m: &PyModule) -> PyResult<()> {
//     m.add_class::<PyFilter>()?;
//     Ok(())
// }
