use csv;
use rand::Rng;
use std::error::Error;
use std::fs::File;
use std::io::Write;
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex};
use std::thread;

const USE_DATA: bool = true;

// -----------------------------------------------------------------------------
// SETUP FOR THE SIMULATED SIGNALS
// -----------------------------------------------------------------------------

const BASELINE_AMPLITUDE: f64 = 70.0;
const SLEEP_TIME: u64 = 100;
const INCREMENT_TIME: f64 = 0.1;

const BACKGROUND_I_FREQ: f64 = 0.5;
const BACKGROUND_II_FREQ: f64 = 1.0;
const BACKGROUND_III_FREQ: f64 = 2.0;
const SHARP_WAVE_RIPPLE_FREQ: f64 = 13.0;
const INTERICTAL_SPIKE_FREQ: f64 = 3.0;
const SLOW_WAVE_FREQ: f64 = 0.5;

#[derive(Debug)]
struct PulseParams {
    amplitude: f64,
    frequency: f64,
    iterations: usize,
    start_phase: f64,
}

impl PulseParams {
    fn new(amplitude: f64, frequency: f64, iterations: usize, start_phase: f64) -> Self {
        Self {
            amplitude,
            frequency,
            iterations,
            start_phase,
        }
    }
}

// -----------------------------------------------------------------------------
// SETUP FOR INPORTING SIGNALS FROM CSV
// -----------------------------------------------------------------------------

const NUM_SIGNALS: usize = 3;

fn read_signals_from_csv(file_path: &str) -> Result<Vec<Vec<f32>>, Box<dyn Error>> {
    let mut rdr = csv::Reader::from_reader(File::open(file_path)?);
    let mut data: Vec<Vec<f32>> = vec![Vec::new(); NUM_SIGNALS]; // Create a vector of 10 empty vectors

    for result in rdr.records() {
        let record = result?;
        for (index, value) in record.iter().enumerate() {
            data[index].push(value.parse()?);
        }
    }

    Ok(data)
}

// -----------------------------------------------------------------------------
// RUN CODE
// -----------------------------------------------------------------------------

pub fn run() -> std::io::Result<()> {
    let listener = TcpListener::bind("127.0.0.1:8080")?;
    let mut rng = rand::thread_rng();

    let signal_data = read_signals_from_csv("data/signals.csv").unwrap();

    for stream in listener.incoming() {
        let stream = stream?;
        let stream_mutex = Arc::new(Mutex::new(Some(stream)));

        let mut time = 0.0;

        loop {
            let random_signal = rng.gen_range(-10..10) as f64;
            let n = (10.0 * (BACKGROUND_I_FREQ * time).sin()
                + BASELINE_AMPLITUDE / 2.0 * (BACKGROUND_II_FREQ * time).sin()
                + BASELINE_AMPLITUDE)
                + 5.0 * (BACKGROUND_III_FREQ * time).sin()
                + random_signal;
            let n = n as i32;

            // Capture the baseline amplitude
            let baseline_amplitude = n as f64;

            {
                let mut locked_stream = stream_mutex.lock().unwrap();

                // Check if the stream is available (not being used by send_pulse)
                if let Some(stream) = locked_stream.as_mut() {
                    // write the number into the stream as bytes
                    stream.write(&n.to_be_bytes())?;
                }
            }

            // Determine if a pulse should be sent
            if rng.gen_range(0..100) < 2 {
                // 2% chance
                let pulse_params = match rng.gen_range(0..3) {
                    0 => PulseParams::new(30.0, SHARP_WAVE_RIPPLE_FREQ, 30, 0.0),
                    1 => PulseParams::new(40.0, INTERICTAL_SPIKE_FREQ, 8, std::f64::consts::PI),
                    2 => PulseParams::new(30.0, SLOW_WAVE_FREQ, 48, 0.0),
                    _ => unreachable!(), // Should never happen with the above range
                };

                let stream_mutex_clone = Arc::clone(&stream_mutex);
                thread::spawn(move || {
                    let mut locked_stream = stream_mutex_clone.lock().unwrap();
                    if let Some(stream) = locked_stream.take() {
                        let stream = send_pulse(stream, &pulse_params, baseline_amplitude).unwrap();
                        *locked_stream = Some(stream);
                    }
                });
            }

            // Sleep between iterations, increment time
            std::thread::sleep(std::time::Duration::from_millis(SLEEP_TIME));
            time += INCREMENT_TIME;
        }
    }

    Ok(())
}

fn simulated_loop() -> {
    
}

fn send_pulse(
    mut stream: TcpStream,
    params: &PulseParams,
    baseline_amplitude: f64,
) -> std::io::Result<TcpStream> {
    let PulseParams {
        amplitude,
        frequency,
        iterations,
        start_phase,
    } = params;

    let amplitude = *amplitude;
    let frequency = *frequency;
    let iterations = *iterations;
    let start_phase = *start_phase;

    let mut time = 0.0;
    let mut rng = rand::thread_rng();

    for _ in 0..iterations {
        // Generating a sinusoidal pulse signal
        let signal_value = baseline_amplitude
            + (amplitude * f64::sin(2.0 * std::f64::consts::PI * frequency * time + start_phase));

        // Adding random noise
        let signal_value = signal_value as i32 + rng.gen_range(-5..5);

        // Convert the signal_value into bytes
        let signal_bytes = signal_value.to_be_bytes();
        stream.write(&signal_bytes)?;

        // Sleep between iterations, increment time
        std::thread::sleep(std::time::Duration::from_millis(SLEEP_TIME));
        time += INCREMENT_TIME;
    }

    Ok(stream)
}
