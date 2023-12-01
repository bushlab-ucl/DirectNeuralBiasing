// // Biquad bandpass filter, cascaded style with 5 coefficients each for 'a' and 'b'
// pub struct BandPassFilterCascaded {
//     a: [f64; 5],
//     b: [f64; 5],
//     x: [f64; 5],
//     y: [f64; 5],
// }

// impl BandPassFilterCascaded {
//     // Create a new filter with custom coefficients
//     pub fn new_custom(b_coeffs: [f64; 5], a_coeffs: [f64; 5]) -> Self {
//         BandPassFilterCascaded {
//             b: b_coeffs,
//             a: a_coeffs,
//             x: [0.0; 5],
//             y: [0.0; 5],
//         }
//     }

//     // Getter for 'b' coefficients
//     pub fn get_b_coeffs(&self) -> [f64; 5] {
//         self.b
//     }

//     // Getter for 'a' coefficients
//     pub fn get_a_coeffs(&self) -> [f64; 5] {
//         self.a
//     }

//     // Setter for 'b' coefficients
//     pub fn set_b_coeffs(&mut self, coeffs: [f64; 5]) {
//         self.b = coeffs;
//     }

//     // Setter for 'a' coefficients
//     pub fn set_a_coeffs(&mut self, coeffs: [f64; 5]) {
//         self.a = coeffs;
//     }

//     // Filter an input sample and update the internal state
//     pub fn process_sample(&mut self, input: f64) -> f64 {
//         // Shift the x and y arrays
//         for i in (1..5).rev() {
//             self.x[i] = self.x[i - 1];
//             self.y[i] = self.y[i - 1];
//         }

//         // Update the current input
//         self.x[0] = input;

//         // Apply the filter equation
//         let output = (0..5)
//             .map(|i| self.b[i] * self.x[i] - self.a[i] * self.y[i])
//             .sum();

//         // Update the current output
//         self.y[0] = output;

//         output
//     }

//     // Create a Butterworth bandpass filter with specified parameters
//     pub fn butterworth(f0: f64, fs: f64) -> Self {
//         let q = (2.0f64).sqrt() / 2.0; // Buttterworth, maximally flat response
//                                        // Compute coefficients for high-pass and low-pass filters
//         let hp_coeffs = Self::high_pass(f0, fs, q);
//         let lp_coeffs = Self::low_pass(f0, fs, q);

//         // Combine coefficients through cascading
//         let mut combined_b = [0.0; 5];
//         let mut combined_a = [0.0; 5];

//         // Simple cascading by multiplication of coefficients
//         for i in 0..5 {
//             combined_b[i] = hp_coeffs[i] * lp_coeffs[i];
//             combined_a[i] = hp_coeffs[i] + lp_coeffs[i];
//         }

//         BandPassFilterCascaded {
//             a: combined_a,
//             b: combined_b,
//             x: [0.0; 5],
//             y: [0.0; 5],
//         }
//     }

//     // High-pass filter coefficients
//     pub fn high_pass(f0: f64, fs: f64, q: f64) -> [f64; 5] {
//         let omega = 2.0 * std::f64::consts::PI * f0 / fs;
//         let alpha = f64::sin(omega) / (2.0 * q);
//         let a0 = 1.0 + alpha;

//         [
//             (1.0 + f64::cos(omega)) / 2.0 / a0,
//             -(1.0 + f64::cos(omega)) / a0,
//             (1.0 + f64::cos(omega)) / 2.0 / a0,
//             -2.0 * f64::cos(omega) / a0,
//             (1.0 - alpha) / a0,
//         ]
//     }

//     // Low-pass filter coefficients
//     pub fn low_pass(f0: f64, fs: f64, q: f64) -> [f64; 5] {
//         let omega = 2.0 * std::f64::consts::PI * f0 / fs;
//         let alpha = f64::sin(omega) / (2.0 * q);
//         let a0 = 1.0 + alpha;

//         [
//             (1.0 - f64::cos(omega)) / 2.0 / a0,
//             (1.0 - f64::cos(omega)) / a0,
//             (1.0 - f64::cos(omega)) / 2.0 / a0,
//             -2.0 * f64::cos(omega) / a0,
//             (1.0 - alpha) / a0,
//         ]
//     }
// }

// // Usage example
// // let mut filter = BandPassFilter::butterworth(1000.0, 44100.0, 1.0);
// // let filtered_sample = filter.process_sample(input_sample);
