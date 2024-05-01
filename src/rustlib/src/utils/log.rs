use std::fs::OpenOptions;
use std::io::{Result, Write};

// allow dead code for now
#[allow(dead_code)]
pub fn log_to_file(msg: &str) -> Result<()> {
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open("log.txt")?;

    writeln!(file, "{}", msg)?;
    Ok(())
}
