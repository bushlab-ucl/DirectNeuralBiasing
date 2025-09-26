# Real-Time Neural Processing with Blackrock Integration

This C++ application provides real-time closed-loop stimulation for neural electrophysiology experiments. It interfaces with Blackrock Microsystems hardware to capture neural signals, processes them using a Rust-based signal processing library, and triggers audio stimulation based on detected neural events.

## Overview

The system implements a dual-buffer architecture for real-time neural signal processing:
1. **Data Acquisition Thread**: Continuously captures neural data from Blackrock hardware
2. **Processing Thread**: Analyzes neural signals and triggers stimulation events
3. **Audio Scheduling**: Provides precise timing for closed-loop stimulation

## Architecture

```
Blackrock Hardware → CBSDK → C++ Data Acquisition → Dual Buffer System → Rust Signal Processor → Audio Stimulation
```

### Key Components

#### 1. Blackrock Integration (CBSDK)
- Connects to Blackrock neural recording systems via UDP (preferred) or Central
- Non-invasive approach: uses existing channel configurations to avoid conflicts with recording software
- Supports both live data streams and nPlay file playback

#### 2. Dual Buffer System
- **Buffer A** and **Buffer B** alternate between filling and processing
- Thread-safe synchronization prevents data loss during real-time processing
- Fixed buffer size of 4096 samples for consistent latency

#### 3. Rust Signal Processing Engine
- Loaded as a DLL (`direct_neural_biasing.dll`)
- Configurable via YAML files for filters, detectors, and triggers
- Returns precise timestamps for stimulation timing

#### 4. Audio Stimulation
- Schedules audio pulses at precise future timestamps
- Uses Windows `PlaySound` API for low-latency audio output
- Asynchronous scheduling prevents blocking the main processing loop

## Configuration

### config.yaml Structure
```yaml
processor:
  verbose: true
  fs: 30000.0        # Sampling frequency (Hz)
  channel: 65        # Blackrock channel number (1-based)
  enable_debug_logging: true

filters:
  bandpass_filters:
    - id: slow_wave_filter
      f_low: 0.5       # Hz
      f_high: 4.0      # Hz

detectors:
  wave_peak_detectors:
    - id: slow_wave_detector
      filter_id: slow_wave_filter
      z_score_threshold: 2.0
      wave_polarity: downwave

triggers:
  pulse_triggers:
    - id: pulse_trigger
      activation_detector_id: slow_wave_detector
      inhibition_detector_id: ""
      pulse_cooldown_ms: 2000.0
```

### Required Files
- `config.yaml`: Signal processing configuration
- `direct_neural_biasing.dll`: Rust processing library
- `pink_noise_short.wav`: Audio stimulation file

## Usage

### Basic Operation
```bash
# Ensure files are in the same directory as the executable
neural_processor.exe
```

### Graceful Shutdown
- Press **Ctrl+C** to stop processing and restore system state
- The application will automatically clean up resources and close connections

## Thread Architecture

### Main Thread (Data Acquisition)
1. Opens connection to Blackrock system
2. Configures data acquisition parameters
3. Continuously fetches neural data in chunks
4. Converts INT16 samples to double precision (µV)
5. Fills available buffers in dual-buffer system

### Processing Thread
1. Waits for filled buffers from main thread
2. Passes data to Rust signal processing engine
3. Receives trigger timestamps for detected events
4. Schedules audio stimulation at precise future times
5. Marks buffers as available for refilling

### Audio Threads (Dynamic)
- Created on-demand for each scheduled audio pulse
- Sleep until target timestamp, then play audio file
- Automatically cleaned up after playback

## Buffer Management

The dual-buffer system prevents data loss during real-time processing:

```cpp
// Simplified buffer logic
while (acquiring_data) {
    wait_for_available_buffer();
    fill_buffer_with_neural_data();
    mark_buffer_ready();
    switch_to_next_buffer();
}

// Processing thread
while (processing) {
    wait_for_ready_buffer();
    process_neural_data();
    schedule_stimulation_if_needed();
    mark_buffer_available();
}
```

## Safety Features

### Recording Software Compatibility
- **UDP-first connection**: Avoids conflicts with Blackrock's Central application
- **Non-invasive configuration**: Uses existing channel settings instead of overriding them
- **Trial configuration checking**: Detects and works with existing data collection setups

### Error Handling
- Graceful degradation when no neural data is available
- Connection type fallback (UDP → Central → Default)
- Comprehensive error reporting with diagnostic information

### Resource Management
- Automatic cleanup on Ctrl+C interrupt
- Thread-safe shutdown procedures
- Memory management for trial buffers

## Performance Considerations

### Real-Time Requirements
- **Buffer size**: 4096 samples (~137ms at 30kHz) balances latency and processing efficiency
- **Processing latency**: Typically <10ms for signal analysis
- **Stimulation precision**: Sub-millisecond timing accuracy for closed-loop applications

### CPU Usage
- Main thread: Minimal CPU usage during data acquisition
- Processing thread: Moderate CPU usage during signal analysis
- Audio threads: Negligible CPU usage

## Troubleshooting

### Common Issues

#### "No trial data available"
- **Live data**: Check channel connectivity and configuration
- **nPlay**: Ensure file is properly loaded and playing
- **Solution**: Verify channel number in `config.yaml` matches connected channels

#### "Failed to load Rust DLL"
- Ensure `direct_neural_biasing.dll` is in the same directory
- Check that Visual C++ Redistributables are installed
- Verify DLL architecture matches executable (x64/x86)

#### "Connection failed"
- Verify Blackrock hardware is connected and powered
- Check that Central application isn't exclusively locking the connection
- Try different connection types (UDP vs Central)

#### Audio stimulation not working
- Ensure `pink_noise_short.wav` exists in the application directory
- Check Windows audio settings and default playback device
- Verify audio file format is compatible with PlaySound API

### Debug Output
The application provides detailed logging:
- Connection type and status
- Channel configuration details
- Buffer processing statistics
- Trigger event timestamps
- Error codes and descriptions

### Performance Monitoring
```
Processing time: 8 ms
Scheduling audio pulse in 1250 ms
Channel 65 sample rate: 30000 Hz
Trial initialized - Channel count: 1
```

## Development Notes

### Dependencies
- **Windows SDK**: For PlaySound and system APIs
- **Blackrock CBSDK**: Neural hardware interface
- **Rust DLL**: Signal processing engine
- **C++17**: Modern C++ features for threading and timing

### Compilation Requirements
- Visual Studio 2019 or newer
- Blackrock CBSDK headers and libraries
- Windows 10 SDK

### Extension Points
- **Custom audio**: Replace PlaySound with ASIO or other low-latency audio APIs
- **Multiple channels**: Extend configuration to process multiple neural channels
- **Network stimulation**: Replace audio with network commands to stimulation devices
- **Custom processing**: Modify Rust library for different signal processing algorithms

## License

This code is part of the Direct Neural Biasing project developed by the Human Electrophysiology Lab at UCL. See project license for usage terms.