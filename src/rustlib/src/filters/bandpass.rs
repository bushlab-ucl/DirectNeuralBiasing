// Biquad bandpass filter, 2nd order
pub struct BandPassFilter {
    a: [f64; 3],
    b: [f64; 3],
    x: [f64; 2],
    y: [f64; 2],
}

#[allow(dead_code)]
impl BandPassFilter {
    // Create a new bandpass filter - Basic. Higher q for sharper rolloff (more prone to ringing). Lower q for smoother rolloff (less sharp).
    pub fn biquad(f0: f64, fs: f64, q: f64) -> Self {
        let omega = 2.0 * std::f64::consts::PI * f0 / fs;
        let alpha = f64::sin(omega) / (2.0 * q);

        let b0 = q * alpha;
        let b1 = 0.0;
        let b2 = -q * alpha;
        let a0 = 1.0 + alpha;
        let a1 = -2.0 * f64::cos(omega);
        let a2 = 1.0 - alpha;

        BandPassFilter {
            a: [a0, a1, a2],
            b: [b0, b1, b2],
            x: [0.0, 0.0],
            y: [0.0, 0.0],
        }
    }

    // Butterworth filter, Q set to sqrt(2)/2. This is the most commonly used filter, as it has a maximally flat response in the passband.
    pub fn butterworth(f0: f64, fs: f64) -> Self {
        let q = (2.0f64).sqrt() / 2.0;
        return Self::biquad(f0, fs, q);
    }

    // Chebyshev filter. This filter has a steeper rolloff than the Butterworth filter, but has ripples in the passband.
    // (0.1dB - 1dB is typical. 0.1dB is sharper, but more prone to ringing, 1dB is smoother, but less sharp).
    pub fn chebyshev(f0: f64, fs: f64, q: f64) -> Self {
        let epsilon = (10.0f64.powf(0.1 * q) - 1.0).sqrt();
        let v0 = 2.0 * std::f64::consts::PI * f0 / fs;
        let sinh = ((epsilon * epsilon + 1.0).sqrt()).ln() / (2.0 * epsilon);
        let sin_omega =
            (0.5 * (v0.sinh() * sinh).exp() - 0.5 * (v0.sinh() * sinh).exp().recip()).abs();
        let cos_omega =
            (0.5 * (v0.sinh() * sinh).exp() + 0.5 * (v0.sinh() * sinh).exp().recip()) / 2.0;

        let b0 = sin_omega / (1.0 + cos_omega);
        let b1 = 0.0;
        let b2 = -sin_omega / (1.0 + cos_omega);
        let a0 = 1.0;
        let a1 = -2.0 * cos_omega / (1.0 + cos_omega);
        let a2 = (1.0 - sin_omega) / (1.0 + cos_omega);

        BandPassFilter {
            a: [a0, a1, a2],
            b: [b0, b1, b2],
            x: [0.0, 0.0],
            y: [0.0, 0.0],
        }
    }

    // Filter an input sample and update the internal state
    pub fn filter(&mut self, input: f64) -> f64 {
        let output = (self.b[0] / self.a[0]) * input
            + (self.b[1] / self.a[0]) * self.x[0]
            + (self.b[2] / self.a[0]) * self.x[1]
            - (self.a[1] / self.a[0]) * self.y[0]
            - (self.a[2] / self.a[0]) * self.y[1];

        // Shift the x and y arrays to accommodate the new sample
        self.x[1] = self.x[0];
        self.x[0] = input;
        self.y[1] = self.y[0];
        self.y[0] = output;

        output
    }
}
