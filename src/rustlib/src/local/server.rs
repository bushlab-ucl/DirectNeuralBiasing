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
// SETUP FOR INPORTING SIGNALS FROM CSV
// -----------------------------------------------------------------------------

const NUM_SIGNALS: usize = 1;

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
    // print current dir

    // make current dir to the crate root
    std::env::set_current_dir(
        std::env::current_exe()
            .unwrap()
            .parent()
            .unwrap()
            .parent()
            .unwrap(),
    )
    .unwrap();
    println!("{:?}", std::env::current_dir().unwrap());

    // read data
    let signal_data = if USE_DATA {
        Arc::new(read_signals_from_csv("../data/signals.csv").unwrap())
    } else {
        Arc::new(Vec::new()) // Use an empty vector when not using CSV data
    };

    for stream in listener.incoming() {
        let stream = stream?;
        let stream_mutex = Arc::new(Mutex::new(Some(stream)));

        if USE_DATA {
            // CSV data mode
            let stream_mutex_clone = Arc::clone(&stream_mutex);
            let signal_data_clone = Arc::clone(&signal_data); // Clone the Arc
            thread::spawn(move || {
                send_csv_data(stream_mutex_clone, signal_data_clone).unwrap(); // Use the clone inside the closure
            });
        } else {
            // Simulated signal mode
            let stream_mutex_clone = Arc::clone(&stream_mutex);
            thread::spawn(move || {
                simulated_loop(stream_mutex_clone).unwrap();
            });
        }
    }

    Ok(())
}

// -----------------------------------------------------------------------------
// SENDING DATA FROM CSV
// -----------------------------------------------------------------------------

fn send_csv_data(
    stream_mutex: Arc<Mutex<Option<TcpStream>>>,
    data: Arc<Vec<Vec<f32>>>,
) -> std::io::Result<()> {
    let mut time_index = 0;
    loop {
        let mut locked_stream = stream_mutex.lock().unwrap();
        if let Some(stream) = locked_stream.as_mut() {
            // Assume data is structured such that each Vec<f32> is one signal channel
            // and time_index iterates over each time step
            if time_index < data[0].len() {
                // all channels
                // for channel_data in data.iter() {
                //     let signal_value = channel_data[time_index] as i32;
                //     // print value type = [u8; 4]
                //     println!("{:?}", signal_value.to_be_bytes());

                //     stream.write(&signal_value.to_be_bytes())?;
                // }

                // only last channel
                let signal_value = data[NUM_SIGNALS - 1][time_index] as i32;
                stream.write(&signal_value.to_be_bytes())?;

                time_index += 1;
            } else {
                break; // Stop the loop when the end of the data is reached
            }
        }
        std::thread::sleep(std::time::Duration::from_millis(SLEEP_TIME));
    }
    Ok(())
}

// -----------------------------------------------------------------------------
// SETUP FOR THE SIMULATED SIGNALS
// -----------------------------------------------------------------------------

const BASELINE_AMPLITUDE: f64 = 70.0;
const SLEEP_TIME: u64 = 10;
const INCREMENT_TIME: f64 = 0.1;

const BACKGROUND_I_FREQ: f64 = 0.5;
const BACKGROUND_II_FREQ: f64 = 1.0;
const BACKGROUND_III_FREQ: f64 = 2.0;
const SHARP_WAVE_RIPPLE_FREQ: f64 = 13.0;
const INTERICTAL_SPIKE_FREQ: f64 = 3.0;
const SLOW_WAVE_FREQ: f64 = 0.5;

#[derive(Debug)]
pub struct PulseParams {
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
// SIMULATING DATA
// -----------------------------------------------------------------------------

fn simulated_loop(stream_mutex: Arc<Mutex<Option<TcpStream>>>) -> std::io::Result<()> {
    let mut rng = rand::thread_rng();

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
