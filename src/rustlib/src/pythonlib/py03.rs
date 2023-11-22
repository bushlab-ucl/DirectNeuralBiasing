use crate::filters::bandpass::BandPassFilter;
use pyo3::prelude::*;
use pyo3::{wrap_pyfunction, wrap_pymodule};

#[pymodule]
#[pyo3(name = "dnb")]
fn dnb(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_wrapped(wrap_pymodule!(filters_module))?;
    Ok(())
}

#[pymodule]
#[pyo3(name = "filters")]
fn filters_module(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(with_bounds_coeffs, m)?)?;
    m.add_function(wrap_pyfunction!(butterworth_coeffs, m)?)?;
    m.add_function(wrap_pyfunction!(biquad_coeffs, m)?)?;
    m.add_function(wrap_pyfunction!(chebyshev_coeffs, m)?)?;
    m.add_function(wrap_pyfunction!(apply_filter, m)?)?;
    Ok(())
}

#[pyfunction]
fn with_bounds_coeffs(bounds: Vec<f64>, fs: f64) -> PyResult<(Vec<f64>, Vec<f64>)> {
    let filter = BandPassFilter::with_bounds(bounds, fs);
    Ok((
        filter.get_b_coeffs().to_vec(),
        filter.get_a_coeffs().to_vec(),
    ))
}

#[pyfunction]
fn butterworth_coeffs(f0: f64, fs: f64) -> PyResult<(Vec<f64>, Vec<f64>)> {
    let filter = BandPassFilter::butterworth(f0, fs);
    Ok((
        filter.get_b_coeffs().to_vec(),
        filter.get_a_coeffs().to_vec(),
    ))
}

#[pyfunction]
fn biquad_coeffs(f0: f64, fs: f64, q: f64) -> PyResult<(Vec<f64>, Vec<f64>)> {
    let filter = BandPassFilter::biquad(f0, fs, q);
    Ok((
        filter.get_b_coeffs().to_vec(),
        filter.get_a_coeffs().to_vec(),
    ))
}

#[pyfunction]
fn chebyshev_coeffs(f0: f64, fs: f64, q: f64) -> PyResult<(Vec<f64>, Vec<f64>)> {
    let filter = BandPassFilter::chebyshev(f0, fs, q);
    Ok((
        filter.get_b_coeffs().to_vec(),
        filter.get_a_coeffs().to_vec(),
    ))
}

#[pyfunction]
fn apply_filter(b_coeffs: Vec<f64>, a_coeffs: Vec<f64>, signal: Vec<f64>) -> PyResult<Vec<f64>> {
    if b_coeffs.len() != 3 || a_coeffs.len() != 3 {
        return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            "b and a coefficients must each have 3 elements.",
        ));
    }

    let mut filter = BandPassFilter::new_custom(
        [b_coeffs[0], b_coeffs[1], b_coeffs[2]],
        [a_coeffs[0], a_coeffs[1], a_coeffs[2]],
    );

    let mut filtered_signal = Vec::with_capacity(signal.len());
    for &sample in signal.iter() {
        let filtered_sample = filter.process_sample(sample);
        filtered_signal.push(filtered_sample);
    }

    Ok(filtered_signal)
}
