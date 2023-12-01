use crate::processing::process_signal::PyFilterState;
use pyo3::prelude::*;

pub mod filters;
pub mod processing;

#[pymodule]
fn dnb(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyFilterState>()?;
    Ok(())
}
