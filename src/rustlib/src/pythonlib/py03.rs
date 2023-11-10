use crate::filters::bandpass::BandPassFilter;

// #[cfg(feature = "python-extension")]
use pyo3::prelude::*;
// #[cfg(feature = "python-extension")]
use pyo3::{wrap_pyfunction, wrap_pymodule};

// #[cfg(feature = "python-extension")]
#[pymodule]
#[pyo3(name = "dnb")]
fn dnb(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pymodule!(filters_module))?;
    Ok(())
}

// #[cfg(feature = "python-extension")]
#[pymodule]
#[pyo3(name = "filters")]
fn filters_module(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(butterworth_filter, m)?)?;
    m.add_function(wrap_pyfunction!(biquad_filter, m)?)?;
    m.add_function(wrap_pyfunction!(chebyshev_filter, m)?)?;
    Ok(())
}

// #[cfg(feature = "python-extension")]
#[pyfunction]
#[pyo3(name = "butterworth")]
fn butterworth_filter(f0: f64, fs: f64, signal: Vec<f64>) -> PyResult<Vec<f64>> {
    let mut butterworth = BandPassFilter::butterworth(f0, fs);

    // Add your own code to generate or fetch the input data
    // let input_data = vec![0.0, 1.0, 2.0]; // Placeholder

    let mut filered_signal = vec![];
    for value in signal {
        let filtered = butterworth.process_sample(value);
        filered_signal.push(filtered);
    }

    Ok(filered_signal)
}

// #[cfg(feature = "python-extension")]
#[pyfunction]
#[pyo3(name = "biquad")]
fn biquad_filter(f0: f64, fs: f64, q: f64, signal: Vec<f64>) -> PyResult<Vec<f64>> {
    let mut biquad = BandPassFilter::biquad(f0, fs, q);

    // Add your own code to generate or fetch the input data
    // let input_data = vec![0.0, 1.0, 2.0]; // Placeholder

    let mut filered_signal = vec![];
    for value in signal {
        let filtered = biquad.process_sample(value);
        filered_signal.push(filtered);
    }

    Ok(filered_signal)
}

// #[cfg(feature = "python-extension")]
#[pyfunction]
#[pyo3(name = "chebyshev")]
fn chebyshev_filter(f0: f64, fs: f64, q: f64, signal: Vec<f64>) -> PyResult<Vec<f64>> {
    let mut chebyshev = BandPassFilter::chebyshev(f0, fs, q);

    // Add your own code to generate or fetch the input data
    // let input_data = vec![0.0, 1.0, 2.0]; // Placeholder

    let mut filered_signal = vec![];
    for value in signal {
        let filtered = chebyshev.process_sample(value);
        filered_signal.push(filtered);
    }

    Ok(filered_signal)
}
