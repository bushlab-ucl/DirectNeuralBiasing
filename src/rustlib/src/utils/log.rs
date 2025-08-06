// src/utils/log.rs

use std::fs::{OpenOptions, remove_file}; // Import remove_file
use std::io::{self, Write, ErrorKind}; // Import ErrorKind
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

/// Logs a message to a file with timestamp
///
/// # Arguments
///
/// * `filename` - The name of the log file (will be created in the current directory)
/// * `message` - The message to log
///
/// # Returns
///
/// * `io::Result<()>` - Success or error result
pub fn log_to_file(filename: &str, message: &str) -> io::Result<()> {
    // Create directory if it doesn't exist
    let log_dir = "logs";
    if !Path::new(log_dir).exists() {
        std::fs::create_dir_all(log_dir)?;
    }

    let path = format!("{}/{}", log_dir, filename);

    // Open file in append mode, create if it doesn't exist
    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;

    // Get current timestamp
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs();

    // Write to the file with timestamp header
    writeln!(file, "\n--- Log entry at {} ---", timestamp)?;
    writeln!(file, "{}", message)?;
    writeln!(file, "--- End of entry ---\n")?;

    // Ensure the data is written to disk
    file.flush()?;

    Ok(())
}

/// Logs a message to a file with a detailed formatted header
///
/// # Arguments
///
/// * `filename` - The name of the log file
/// * `header` - A descriptive header for this log entry
/// * `message` - The message to log
///
/// # Returns
///
/// * `io::Result<()>` - Success or error result
#[allow(dead_code)]
pub fn log_with_header(filename: &str, header: &str, message: &str) -> io::Result<()> {
    let formatted_message = format!(
        "===== {} =====\n{}\n====================",
        header, message
    );
    log_to_file(filename, &formatted_message)
}

/// Appends data to a CSV file, creating headers if the file is new
///
/// # Arguments
///
/// * `filename` - The name of the CSV file
/// * `headers` - Column headers (only written if file is new)
/// * `data` - Row of data to append
///
/// # Returns
///
/// * `io::Result<()>` - Success or error result
#[allow(dead_code)]
pub fn log_csv(filename: &str, headers: &[&str], data: &[&str]) -> io::Result<()> {
    // Create directory if it doesn't exist
    let log_dir = "logs";
    if !Path::new(log_dir).exists() {
        std::fs::create_dir_all(log_dir)?;
    }

    let path = format!("{}/{}", log_dir, filename);
    let file_exists = Path::new(&path).exists();

    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;

    // Write headers if file is new
    if !file_exists && !headers.is_empty() {
        writeln!(file, "{}", headers.join(","))?;
    }

    // Write data row
    writeln!(file, "{}", data.join(","))?;
    file.flush()?;

    Ok(())
}

/// Deletes a log file if it exists. Does not return an error if the file does not exist.
///
/// # Arguments
///
/// * `filename` - The name of the log file to delete (within the "logs" directory).
///
/// # Returns
///
/// * `io::Result<()>` - Success if the file was deleted or didn't exist, or an error if deletion failed for another reason.
#[allow(dead_code)]
pub fn delete_log_file(filename: &str) -> io::Result<()> {
    let log_dir = "logs";
    let path = format!("{}/{}", log_dir, filename);
    
    match remove_file(&path) {
        Ok(_) => {
            // File was successfully deleted
            Ok(())
        },
        Err(e) => {
            // If the error is NotFound, the file didn't exist, which is fine
            if e.kind() == ErrorKind::NotFound {
                Ok(())
            } else {
                // For any other error, propagate it
                Err(e)
            }
        }
    }
}