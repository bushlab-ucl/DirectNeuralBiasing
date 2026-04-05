// src/utils/log.rs

use std::collections::HashMap;
use std::fs::{remove_file, OpenOptions}; // Import remove_file
use std::io::{self, ErrorKind, Write}; // Import ErrorKind
use std::path::Path;
use std::time::Duration;
use std::time::{SystemTime, UNIX_EPOCH};

/// Generates a formatted timestamp string in the format yyyy-mm-dd_hh-mm-ss
/// (filesystem-safe, using hyphens instead of colons)
///
/// # Returns
///
/// * `String` - The formatted timestamp
pub fn generate_formatted_timestamp() -> String {
    let now = SystemTime::now();
    let datetime = chrono::DateTime::<chrono::Utc>::from(now);
    datetime.format("%Y-%m-%d_%H-%M-%S").to_string()
}

/// Generates a log filename with formatted timestamp
///
/// # Arguments
///
/// * `prefix` - The prefix for the log file name
/// * `suffix` - The suffix/extension for the log file name
///
/// # Returns
///
/// * `String` - The complete log filename
pub fn generate_log_filename(prefix: &str, suffix: &str) -> String {
    let timestamp = generate_formatted_timestamp();
    format!("{}_{}.{}", prefix, timestamp, suffix)
}

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
    let mut file = OpenOptions::new().create(true).append(true).open(path)?;

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

/// Logs configuration information to a file
///
/// # Arguments
///
/// * `filename` - The name of the log file
/// * `config_path` - The path to the configuration file
/// * `config_yaml` - The YAML configuration content
///
/// # Returns
///
/// * `io::Result<()>` - Success or error result
pub fn log_config(filename: &str, config_path: &str, config_yaml: &str) -> io::Result<()> {
    let config_log = format!(
        "Signal Processor Config Loaded:\n\
        Config Path: {}\n\
        \n\
        Full Configuration:\n\
        {}",
        config_path, config_yaml
    );

    log_to_file(filename, &config_log)
}

/// Logs a trigger event with context samples
///
/// # Arguments
///
/// * `filename` - The name of the log file
/// * `trigger_id` - The ID of the triggered event
/// * `context_results` - Vector of sample results for context
///
/// # Returns
///
/// * `io::Result<()>` - Success or error result
pub fn log_trigger_event(
    filename: &str,
    trigger_id: &str,
    context_results: &[HashMap<&'static str, f64>],
) -> io::Result<()> {
    // Get current timestamp for the log
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or(Duration::from_secs(0))
        .as_secs_f64();

    // Format the trigger event information
    let mut log_entry = format!("TRIGGER EVENT [{}]\n", timestamp);

    // Add trigger ID
    log_entry.push_str(&format!("Trigger ID: {}\n\n", trigger_id));

    // Log context samples
    log_entry.push_str("CONTEXT SAMPLES:\n");
    log_entry.push_str("================\n");

    for (i, sample_results) in context_results.iter().enumerate() {
        let is_trigger_sample = i == context_results.len() - 1; // Last sample is the trigger
        let marker = if is_trigger_sample {
            " >>> TRIGGER SAMPLE <<<"
        } else {
            ""
        };

        log_entry.push_str(&format!(
            "Sample {} (relative index: {}){}:\n",
            i,
            i as isize - context_results.len() as isize + 1,
            marker
        ));

        // Get index for this sample
        if let Some(&index) = sample_results.get("global:index") {
            log_entry.push_str(&format!("  global:index = {}\n", index));
        }

        // Get timestamp
        if let Some(&timestamp) = sample_results.get("global:timestamp_ms") {
            log_entry.push_str(&format!("  global:timestamp_ms = {}\n", timestamp));
        }

        // Get raw sample
        if let Some(&raw) = sample_results.get("global:raw_sample") {
            log_entry.push_str(&format!("  global:raw_sample = {}\n", raw));
        }

        // Add key detector/trigger values for the trigger sample
        if is_trigger_sample {
            let mut keys: Vec<&&'static str> = sample_results.keys().collect();
            keys.sort();

            for &key in keys {
                if key.contains("detected") || key.contains("triggered") || key.contains("z_score")
                {
                    if let Some(value) = sample_results.get(key) {
                        log_entry.push_str(&format!("  {} = {}\n", key, value));
                    }
                }
            }
        }

        log_entry.push_str("\n");
    }

    log_to_file(filename, &log_entry)
}

/// Logs a message to terminal only (verbose output)
/// Does NOT write to file - this is for runtime diagnostics only
///
/// # Arguments
///
/// * `filename` - Unused (kept for API compatibility)
/// * `message` - The message to print to terminal
/// * `enable_terminal_output` - Whether to print to terminal
///
/// # Returns
///
/// * `io::Result<()>` - Success or error result
pub fn log_verbose(_filename: &str, message: &str, enable_terminal_output: bool) -> io::Result<()> {
    // Only print to terminal if enabled
    // Never write to file - verbose messages are just for runtime diagnostics
    if enable_terminal_output {
        eprintln!("{}", message);
    }

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
    let formatted_message = format!("===== {} =====\n{}\n====================", header, message);
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

    let mut file = OpenOptions::new().create(true).append(true).open(path)?;

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
        }
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
