use colored::Colorize;
use std::collections::VecDeque;
use std::io::{self, Read};
use std::net::TcpStream;

use crate::filters::bandpass::BandPassFilter;

pub fn run() -> io::Result<()> {
    let mut stream = TcpStream::connect("127.0.0.1:8080")?;
    let mut buffer = [0u8; 4];

    let sensitivity = 5;
    let window_size = 10;

    let f0 = 13.0;
    let fs = 40.0;

    let mut butterworth = BandPassFilter::butterworth(f0, fs);

    // Store the last 6 filtered values
    let mut last_vals = VecDeque::with_capacity(4);

    loop {
        match stream.read_exact(&mut buffer) {
            Ok(_) => {
                let raw = i32::from_be_bytes(buffer);
                let filtered = butterworth.process_sample(raw as f64) as i32;

                // Keep track of the last six filtered values
                if last_vals.len() >= window_size {
                    last_vals.pop_front();
                }
                last_vals.push_back(filtered);

                let alert = if last_vals.iter().filter(|&&x| x > sensitivity).count()
                    >= sensitivity as usize
                {
                    "SWR Detected !".red()
                } else {
                    "              ".white()
                };

                // To ensure |repeat| doesn't overflow
                let max_len = 1000;
                let raw_len = (raw.max(0) as usize).min(max_len);
                let filtered_len = (filtered.max(0) as usize).min(max_len);

                let raw_string = "|".repeat(raw_len);
                let filtered_string = "|".repeat(filtered_len);

                let output = if raw < filtered {
                    format!(
                        "{}{}{}{}",
                        alert,
                        raw_string.white(),
                        filtered_string.red(),
                        "\n"
                    )
                } else {
                    format!(
                        "{}{}{}{}",
                        alert,
                        filtered_string.red(),
                        raw_string.white(),
                        "\n"
                    )
                };

                print!("{}", output);
            }
            Err(e) => {
                eprintln!("Failed to receive data: {}", e);
            }
        }
    }
}
