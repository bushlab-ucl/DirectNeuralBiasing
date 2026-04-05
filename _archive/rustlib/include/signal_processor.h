#ifndef SIGNAL_PROCESSOR_H
#define SIGNAL_PROCESSOR_H

#ifdef __cplusplus
extern "C" {
#endif

// Create a signal processor from a configuration file
void* create_signal_processor_from_config(const char* config_path);

// Delete a signal processor
void delete_signal_processor(void* processor_ptr);

// Reset the index of the signal processor
void reset_index(void* processor_ptr);

// Process a chunk of data
// Returns a pointer to a double (trigger timestamp) if a trigger occurred, or NULL if no trigger
void* run_chunk(void* processor_ptr, const double* data, size_t length);

// Log a message to the signal processor's log file
// This allows C++ code to log messages that will appear in the same log file as the Rust signal processor
void log_message(void* processor_ptr, const char* message);

#ifdef __cplusplus
}
#endif

#endif // SIGNAL_PROCESSOR_H 