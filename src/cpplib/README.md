# Real-Time Neural Processing with Blackrock Integration

This C++ application provides real-time closed-loop stimulation for neural electrophysiology experiments. It interfaces with Blackrock Microsystems hardware to capture neural signals, processes them using a Rust-based signal processing library, and triggers audio stimulation based on detected neural events.

## Overview

The system implements a modular, thread-safe architecture for real-time neural signal processing:

1. **Data Acquisition Thread**: Continuously captures neural data from Blackrock hardware
2. **Processing Thread**: Analyzes neural signals and triggers stimulation events
3. **Data Logging Thread** (optional): Saves raw data to disk without blocking real-time processing
4. **Audio Scheduling**: Provides precise timing for closed-loop stimulation

## Architecture

```
Blackrock Hardware → CBSDK → Dual Buffer System → Rust Signal Processor → Audio Stimulation
                                    ↓
                            Data Logger (optional)
```

### Modular Structure

```
project/
├── main.cpp                    # Main application orchestration
├── logger.h                    # Debug logging system with timestamps
├── config_reader.h             # YAML configuration parser
├── data_logger.h               # Real-time data logging (queue-based)
├── buffer_manager.h            # Thread-safe dual buffer system
├── cbsdk.h                     # Blackrock CBSDK headers
├── direct_neural_biasing.dll   # Rust signal processing library
├── config.yaml                 # Signal processing configuration
└── pink_noise_short.wav        # Audio stimulation file
```

### Key Components

#### 1. Logger (logger.h)

- Comprehensive debug logging with timestamps
- Logs to both console and file
- Component-tagged messages (CBSDK, Main, Processing, etc.)
- Thread-safe implementation

#### 2. Config Reader (config_reader.h)

- Parses YAML configuration files
- Extracts channel number and logging preferences
- Validates configuration values

#### 3. Buffer Manager (buffer_manager.h)

- Implements thread-safe dual-buffer system
- **Buffer A** and **Buffer B** alternate between filling and processing
- Prevents data loss during real-time processing
- Fixed buffer size of 4096 samples for consistent latency

#### 4. Data Logger (data_logger.h)

- Optional raw data recording to binary files
- Queue-based architecture with backpressure handling
- **Never drops data** - slows acquisition if disk is too slow
- Saves to `./data/raw_data_chXX_TIMESTAMP.bin`

#### 5. Blackrock Integration (CBSDK)

- **UDP-first connection strategy**: Avoids conflicts with recording software
- **Non-invasive approach**: Uses existing channel configurations
- **Trial detection**: Works with existing trials or creates new ones
- Supports both live data streams and nPlay file playback

#### 6. Rust Signal Processing Engine

- Loaded as a DLL (`direct_neural_biasing.dll`)
- Configurable via YAML files for filters, detectors, and triggers
- Returns precise timestamps for stimulation timing

#### 7. Audio Stimulation

- Schedules audio pulses at precise future timestamps
- Uses Windows `PlaySound` API for low-latency audio output
- Asynchronous scheduling prevents blocking the main processing loop

## Configuration

### config.yaml Structure

```yaml
processor:
  verbose: true
  fs: 512.0 # Sampling frequency (Hz) - must match channel config!
  channel: 1 # Blackrock channel number (1-based)
  enable_debug_logging: true
  save_raw_data: true # Enable raw data logging to ./data/

filters:
  bandpass_filters:
    - id: slow_wave_filter
      f_low: 0.5 # Hz
      f_high: 4.0 # Hz

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
      pulse_cooldown_ms: 2000.0
```

**Important**: The `fs` parameter must match the actual sampling rate of the channel as configured in Central/nPlay. The application will NOT modify channel configurations.

### Required Files

- `config.yaml`: Signal processing configuration
- `direct_neural_biasing.dll`: Rust processing library
- `pink_noise_short.wav`: Audio stimulation file

## Usage

### Basic Operation

```bash
# Ensure all files are in the same directory as the executable
neural_processor.exe
```

### Reading Raw Data Files

The application saves raw data as binary files containing flat arrays of double-precision floats (µV).

**Python:**

```python
import numpy as np
data = np.fromfile('data/raw_data_ch1_20250106_143022.bin', dtype=np.float64)
# data is now a 1D array of voltages in microvolts
```

**MATLAB:**

```matlab
fid = fopen('data/raw_data_ch1_20250106_143022.bin', 'r');
data = fread(fid, Inf, 'double');
fclose(fid);
```

### Graceful Shutdown

- Press **Ctrl+C** to initiate graceful shutdown
- The application will:
  - Stop acquiring new data
  - Flush all remaining data from the logging queue
  - Close all threads cleanly
  - Report final statistics

## Thread Architecture

### Main Thread (Data Acquisition)

1. Opens connection to Blackrock system (UDP → Central fallback)
2. Verifies channel configuration (non-invasive)
3. Checks for existing trial configuration
4. Continuously fetches neural data in chunks
5. Converts INT16 samples to double precision (µV)
6. Fills available buffers in dual-buffer system
7. Queues data for logging (if enabled)

### Processing Thread

1. Waits for filled buffers from main thread
2. Passes data to Rust signal processing engine
3. Receives trigger timestamps for detected events
4. Schedules audio stimulation at precise future times
5. Marks buffers as available for refilling

### Data Logging Thread (optional)

1. Waits for data chunks in queue
2. Writes chunks to binary file
3. Applies backpressure if disk is slow (prevents data loss)
4. Flushes remaining queue on shutdown

### Audio Threads (dynamic)

- Created on-demand for each scheduled audio pulse
- Sleep until target timestamp, then play audio file
- Automatically cleaned up after playback

## Safety Features

### Recording Software Compatibility

The application is designed to run alongside Blackrock's recording software without interference:

- **UDP-first connection**: Attempts UDP before Central to avoid connection conflicts
- **Non-invasive configuration**: Never modifies channel settings - uses whatever is already configured
- **Trial configuration checking**: Detects existing trials and uses them instead of creating conflicting configurations
- **No state restoration**: Since nothing is modified, nothing needs to be restored on exit

### Error Handling

- Comprehensive debug logging with timestamps and component tags
- Graceful degradation when no neural data is available
- Connection type fallback (UDP → Central)
- Detailed error codes and descriptions

### Resource Management

- Automatic cleanup on Ctrl+C interrupt
- Thread-safe shutdown procedures
- Memory management for trial buffers
- Queue-based logging prevents data loss

## Performance Considerations

### Real-Time Requirements

- **Buffer size**: 4096 samples (~8 seconds at 512Hz, ~137ms at 30kHz)
- **Processing latency**: Typically <10ms for signal analysis
- **Stimulation precision**: Sub-millisecond timing accuracy for closed-loop applications

### Data Logging Performance

- **Queue size**: 1000 chunks (~4MB buffer)
- **Disk requirements**: ~240 KB/s sustained write speed for 30kHz data
- **Backpressure handling**: Slows acquisition if disk cannot keep up (prevents data loss)

### CPU Usage

- Main thread: Minimal CPU usage during data acquisition
- Processing thread: Moderate CPU usage during signal analysis
- Logging thread: Low CPU usage, I/O bound
- Audio threads: Negligible CPU usage

## Debug Logging

All operations are logged with timestamps and component tags:

```
[2025-01-06 14:30:15.123] [INFO] [Main] ===== Application Starting =====
[2025-01-06 14:30:15.234] [INFO] [ConfigReader] Channel: 1
[2025-01-06 14:30:15.345] [INFO] [CBSDK] Attempting UDP connection (multi-app safe)
[2025-01-06 14:30:15.456] [INFO] [CBSDK] Connected via: Central
[2025-01-06 14:30:15.567] [INFO] [BufferManager] Initialized with 2 buffers of size 4096
[2025-01-06 14:30:15.678] [INFO] [DataLogger] Starting data logging to: ./data/raw_data_ch1_20250106_143015.bin
[2025-01-06 14:30:15.789] [INFO] [Main] ===== Entering Main Acquisition Loop =====
[2025-01-06 14:30:20.123] [DEBUG] [Processing] Chunk processed in 8 ms
[2025-01-06 14:30:20.234] [INFO] [Audio] Scheduling pulse in 1250 ms
```

Logs are saved to `./logs/debug_DATE.log`

## Troubleshooting

### Common Issues

#### "No trial data available"

**Symptoms**: Application runs but reports no data from CBSDK
**Causes**:

- Channel not properly configured in nPlay/Central
- Wrong channel number in config.yaml
- Data file not playing in nPlay

**Solutions**:

1. Verify channel number matches connected/configured channels
2. Check that data is actually streaming in Central/nPlay
3. Look at debug logs to see the exact error code

#### "Failed to load Rust DLL"

**Symptoms**: Application crashes on startup
**Causes**:

- Missing `direct_neural_biasing.dll`
- Wrong DLL architecture (x64 vs x86)
- Missing Visual C++ Redistributables

**Solutions**:

1. Ensure DLL is in the same directory as executable
2. Verify DLL and executable are both x64 (or both x86)
3. Install Visual C++ 2019 Redistributables

#### "Connection failed"

**Symptoms**: Cannot connect to CBSDK
**Causes**:

- Blackrock hardware not connected/powered
- Central application not running
- NSP not initialized

**Solutions**:

1. Verify hardware is connected and powered
2. Try opening Central application first
3. Check hardware status lights

#### Wrong sampling rate / filter frequencies off

**Symptoms**: Signal processing not working correctly
**Cause**: `fs` in config.yaml doesn't match actual channel sampling rate

**Solution**:

1. Check channel configuration in Central/nPlay
2. Update `fs` in config.yaml to match
3. The application will report the channel's smpgroup - look up what sampling rate this corresponds to

#### Audio stimulation not working

**Symptoms**: No sound when triggers detected
**Causes**:

- Missing `pink_noise_short.wav`
- Wrong audio device selected
- File format incompatible

**Solutions**:

1. Ensure WAV file exists in application directory
2. Check Windows default audio device
3. Verify WAV file is PCM format (not compressed)

#### Data logging slowing down acquisition

**Symptoms**: Warning about full log queue, slower processing
**Cause**: Disk write speed cannot keep up with data rate

**Solutions**:

1. Use faster disk (SSD instead of HDD)
2. Reduce sampling rate if possible
3. Disable logging during critical experiments

## Development Notes

### Dependencies

- **Windows SDK**: For PlaySound and system APIs
- **Blackrock CBSDK**: Neural hardware interface (v7.0+)
- **Rust DLL**: Signal processing engine
- **C++17**: Modern C++ features for threading and timing

### Compilation Requirements

- Visual Studio 2019 or newer
- Blackrock CBSDK headers and libraries
- Windows 10 SDK (10.0.19041.0 or newer)

### Compilation Command

```bash
cl /EHsc /std:c++17 main.cpp /I"path/to/cbsdk/include" /link /LIBPATH:"path/to/cbsdk/lib" cbsdk.lib winmm.lib
```

### Extension Points

- **Custom audio**: Replace PlaySound with ASIO for lower latency
- **Multiple channels**: Extend BufferManager to handle multiple channels
- **Network stimulation**: Replace audio scheduling with network commands
- **Custom processing**: Modify Rust library for different algorithms
- **Real-time visualization**: Add plotting/display thread

## License

This code is part of the Direct Neural Biasing project developed by the Human Electrophysiology Lab at UCL. See project license for usage terms.

## Citation

If you use this software in your research, please cite:

```
[Citation information to be added]
```
