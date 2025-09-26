#define WIN32_LEAN_AND_MEAN // Exclude rarely-used stuff from Windows headers
#define NOMINMAX
#include <windows.h>
#include "cbsdk.h"
#include <iostream>
#include <string>
#include <chrono>
#include <thread>
#include <queue>
#include <mutex>
#include <condition_variable>
#include <mmsystem.h> // For PlaySound API
#include <ctime>      // For printing timestamps
#include <future>     // For async scheduling
#include <vector>     // For storing futures
#include <algorithm>  // For std::remove_if
#include <iomanip>    // For std::setw and std::setfill
#include <sstream>    // For std::ostringstream
#include <fstream>    // For file operations

// ──────────────────────────────────────────────────────────────
//                        Rust FFI declarations
// ──────────────────────────────────────────────────────────────
typedef void *(__cdecl *CreateSignalProcessorFromConfigFunc)(const char *config_path);
typedef void(__cdecl *DeleteSignalProcessorFunc)(void *processor);
typedef void *(__cdecl *RunChunkFunc)(void *processor, const double *data, size_t length);
typedef void(__cdecl *LogMessageFunc)(void *processor, const char *message);

// ──────────────────────────────────────────────────────────────
//                         Global constants
// ──────────────────────────────────────────────────────────────
const size_t buffer_size = 4096; // Buffer size for real-time processing
const size_t num_buffers = 2;    // Number of reusable buffers (double buffering)
const int WAIT_LENGTH_MS = 2000;  // Increased wait time for data to stabilize

// ──────────────────────────────────────────────────────────────
//                           Buffers
// ──────────────────────────────────────────────────────────────
struct Buffer
{
  double data[buffer_size];
  bool ready = false;
};
Buffer buffers[num_buffers];
size_t filling_buffer_index = 0; // Index of the buffer being filled

std::mutex buffer_mutex;
std::condition_variable buffer_cv;
bool stop_processing = false; // Flag to stop the threads

// ──────────────────────────────────────────────────────────────
//                 Utility: read channel from config.yaml
// ──────────────────────────────────────────────────────────────
int get_channel_from_config(const std::string &config_path)
{
  std::ifstream inFile(config_path);
  if (!inFile.is_open())
  {
    std::cerr << "Failed to open " << config_path << " for reading" << std::endl;
    return -1;
  }

  std::string line;
  bool in_processor_block = false;
  while (std::getline(inFile, line))
  {
    // Detect entering/exiting the processor block naïvely
    if (line.find("processor:") != std::string::npos)
    {
      in_processor_block = true;
      continue;
    }
    if (in_processor_block)
    {
      if (line.find(':') != std::string::npos && line.find_first_not_of(" \t") != std::string::npos && line[0] != ' ' && line[0] != '\t')
      {
        // We hit a new top-level key => exit processor block
        break;
      }
      auto pos = line.find("channel:");
      if (pos != std::string::npos)
      {
        std::string num = line.substr(pos + 8); // 8 = len("channel:")
        try
        {
          return std::stoi(num);
        }
        catch (...)
        {
          std::cerr << "Failed to parse channel number from config.yaml" << std::endl;
          return -1;
        }
      }
    }
  }
  std::cerr << "Did not find a channel entry in processor section of config.yaml" << std::endl;
  return -1;
}

// ──────────────────────────────────────────────────────────────
//                 Windows console Ctrl+C handler
// ──────────────────────────────────────────────────────────────
// Global variables for cleanup - removed channel config restoration to avoid conflicts
bool g_trial_configured = false;

BOOL WINAPI ConsoleHandler(DWORD signal)
{
  if (signal == CTRL_C_EVENT)
  {
    std::cout << "\nCTRL+C received – shutting down gracefully…" << std::endl;
    stop_processing = true;
    buffer_cv.notify_all();
    return TRUE;
  }
  return FALSE;
}

// ──────────────────────────────────────────────────────────────
//                       Helper functions
// ──────────────────────────────────────────────────────────────
// Format time with milliseconds for nice logging
std::string format_time_with_ms(const std::chrono::system_clock::time_point &time_point)
{
  std::time_t time_t = std::chrono::system_clock::to_time_t(time_point);
  char time_str[100];
  std::strftime(time_str, sizeof(time_str), "%Y-%m-%d %H:%M:%S", std::localtime(&time_t));
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(time_point.time_since_epoch()) % 1000;
  std::ostringstream oss;
  oss << time_str << '.' << std::setfill('0') << std::setw(3) << ms.count();
  return oss.str();
}

// Play a short WAV file (pink noise burst) asynchronously
void play_audio_pulse()
{
  auto now = std::chrono::system_clock::now();
  std::cout << "Playing audio pulse at system time: " << format_time_with_ms(now) << std::endl;
  const char *sound_file = "./pink_noise_short.wav";
  PlaySoundA(sound_file, NULL, SND_FILENAME | SND_ASYNC);
}

// Schedule audio pulse at UNIX-epoch timestamp (from Rust)
void schedule_audio_pulse(double timestamp)
{
  auto now = std::chrono::system_clock::now();
  auto target_time = std::chrono::system_clock::from_time_t(static_cast<time_t>(timestamp)) +
                     std::chrono::milliseconds(static_cast<int>((timestamp - static_cast<time_t>(timestamp)) * 1000));
  if (target_time <= now)
  {
    std::cout << "Warning: Scheduled time already passed – skipping pulse" << std::endl;
    return;
  }
  auto delay_ms = std::chrono::duration_cast<std::chrono::milliseconds>(target_time - now).count();
  std::cout << "Scheduling audio pulse in " << delay_ms << " ms (for " << format_time_with_ms(target_time) << ")" << std::endl;

  static std::mutex futures_mutex;
  static std::vector<std::future<void>> futures;
  std::lock_guard<std::mutex> lock(futures_mutex);
  futures.push_back(std::async(std::launch::async, [target_time]()
                               {
        std::this_thread::sleep_until(target_time);
        play_audio_pulse(); }));
  // Remove completed futures
  futures.erase(std::remove_if(futures.begin(), futures.end(), [](std::future<void> &f)
                               { return f.wait_for(std::chrono::seconds(0)) == std::future_status::ready; }),
                futures.end());
}

// ──────────────────────────────────────────────────────────────
//                 Buffer processing thread function
// ──────────────────────────────────────────────────────────────
void process_buffer_loop(void *rust_processor, RunChunkFunc run_chunk, LogMessageFunc log_message)
{
  while (true)
  {
    size_t processing_buffer_index;
    
    // FIXED: Better buffer management logic
    {
      std::unique_lock<std::mutex> lock(buffer_mutex);
      buffer_cv.wait(lock, []
                     { return stop_processing || buffers[0].ready || buffers[1].ready; });
      if (stop_processing)
        break;
      
      // Find the ready buffer and mark as being processed
      processing_buffer_index = buffers[0].ready ? 0 : 1;
      buffers[processing_buffer_index].ready = false;
    }

    auto start_time = std::chrono::high_resolution_clock::now();
    void *result = run_chunk(rust_processor, buffers[processing_buffer_index].data, buffer_size);
    auto end_time = std::chrono::high_resolution_clock::now();
    auto processing_time = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();

    if (result != nullptr)
    {
      double timestamp = *reinterpret_cast<double *>(result);
      std::cout << "Processing time: " << processing_time << " ms" << std::endl;
      std::string msg = "C++: Trigger at " + std::to_string(timestamp) + " (processing " + std::to_string(processing_time) + " ms)";
      log_message(rust_processor, msg.c_str());
      schedule_audio_pulse(timestamp);
      delete static_cast<double *>(result);
    }
    
    // Notify that a buffer is now available
    buffer_cv.notify_one();
  }
}

// ──────────────────────────────────────────────────────────────
//                       DLL Loader helper
// ──────────────────────────────────────────────────────────────
bool load_rust_functions(HINSTANCE &hinstLib,
                         CreateSignalProcessorFromConfigFunc &create_signal_processor_from_config,
                         DeleteSignalProcessorFunc &delete_signal_processor,
                         RunChunkFunc &run_chunk,
                         LogMessageFunc &log_message)
{
  hinstLib = LoadLibrary(TEXT("./direct_neural_biasing.dll"));
  Sleep(1000); // Allow Windows to finish loading symbols
  if (!hinstLib)
  {
    std::cerr << "Failed to load Rust DLL!" << std::endl;
    return false;
  }

  create_signal_processor_from_config = (CreateSignalProcessorFromConfigFunc)GetProcAddress(hinstLib, "create_signal_processor_from_config");
  delete_signal_processor = (DeleteSignalProcessorFunc)GetProcAddress(hinstLib, "delete_signal_processor");
  run_chunk = (RunChunkFunc)GetProcAddress(hinstLib, "run_chunk");
  log_message = (LogMessageFunc)GetProcAddress(hinstLib, "log_message");

  if (!create_signal_processor_from_config || !delete_signal_processor || !run_chunk || !log_message)
  {
    std::cerr << "Failed to resolve exported Rust symbols!" << std::endl;
    FreeLibrary(hinstLib);
    return false;
  }
  return true;
}

// ──────────────────────────────────────────────────────────────
//                            main()
// ──────────────────────────────────────────────────────────────
int main(int argc, char *argv[])
{
  // Handle CTRL+C gracefully
  SetConsoleCtrlHandler(ConsoleHandler, TRUE);

  // ── Load Rust DLL ─────────────────────────────────────────
  HINSTANCE hinstLib;
  CreateSignalProcessorFromConfigFunc create_signal_processor_from_config;
  DeleteSignalProcessorFunc delete_signal_processor;
  RunChunkFunc run_chunk;
  LogMessageFunc log_message;

  if (!load_rust_functions(hinstLib, create_signal_processor_from_config, delete_signal_processor, run_chunk, log_message))
  {
    return 1;
  }

  // ── Open Blackrock CBSDK connection (FIXED: Use UDP to avoid Central conflicts) ──────
  std::cout << "Attempting to open CBSDK with UDP connection to avoid recording software conflicts…" << std::endl;
  cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_UDP);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cout << "UDP connection failed, trying Central..." << std::endl;
    res = cbSdkOpen(0, CBSDKCONNECTION_CENTRAL);
    if (res != CBSDKRESULT_SUCCESS)
    {
      std::cout << "Central connection failed, trying default..." << std::endl;
      res = cbSdkOpen(0, CBSDKCONNECTION_DEFAULT);
      if (res != CBSDKRESULT_SUCCESS)
      {
        std::cerr << "ERROR: All connection types failed (code " << res << ")" << std::endl;
        return 1;
      }
    }
  }
  
  // Report connection type
  cbSdkConnectionType conType;
  cbSdkInstrumentType instType;
  cbSdkGetType(0, &conType, &instType);
  std::cout << "CBSDK connected via: " << (conType == CBSDKCONNECTION_CENTRAL ? "Central" : 
                                          conType == CBSDKCONNECTION_UDP ? "UDP" : "Default") << std::endl;

  // ── Read channel from config.yaml ────────────────────────
  const char *config_path = "./config.yaml";
  int channel = get_channel_from_config(config_path);
  if (channel <= 0)
  {
    std::cerr << "Falling back to channel 65." << std::endl;
    channel = 65;
  }
  std::cout << "Using channel " << channel << " from config.yaml" << std::endl;

  // ── Create Rust signal processor ─────────────────────────
  void *rust_processor = create_signal_processor_from_config(config_path);
  if (!rust_processor)
  {
    std::cerr << "Failed to create Rust signal processor from " << config_path << std::endl;
    cbSdkClose(0);
    return 1;
  }
  log_message(rust_processor, "C++: Signal processor created from config.yaml");

  // ── Check existing channel configuration (FIXED: Non-invasive approach) ──────────────
  cbPKT_CHANINFO chan_info;
  res = cbSdkGetChannelConfig(0, channel, &chan_info);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cerr << "ERROR: cbSdkGetChannelConfig failed (code " << res << ")" << std::endl;
    std::cerr << "Channel " << channel << " may not exist or be available" << std::endl;
    delete_signal_processor(rust_processor);
    cbSdkClose(0);
    return 1;
  }

  // Check if channel is properly configured and connected
  std::cout << "Channel " << channel << " capabilities: 0x" << std::hex << chan_info.chancaps << std::dec << std::endl;
  std::cout << "Channel " << channel << " connected: " << ((chan_info.chancaps & cbCHAN_CONNECTED) ? "Yes" : "No") << std::endl;
  std::cout << "Channel " << channel << " current sample group: " << chan_info.smpgroup << std::endl;

  if (!(chan_info.chancaps & cbCHAN_CONNECTED))
  {
    std::cerr << "WARNING: Channel " << channel << " is not connected!" << std::endl;
  }

  // FIXED: Don't modify channel configuration - use whatever is already set
  log_message(rust_processor, "C++: Using existing channel configuration to avoid conflicts");

  // ── Check trial configuration (FIXED: Non-invasive approach) ──────────────────────────
  uint32_t bActive = 0;
  uint16_t begchan, endchan;
  uint32_t begmask, begval, endmask, endval;
  bool bDouble, bAbsolute;
  uint32_t uWaveforms, uConts, uEvents, uComments, uTrackings;
  
  res = cbSdkGetTrialConfig(0, &bActive, &begchan, &begmask, &begval, 
                           &endchan, &endmask, &endval, &bDouble,
                           &uWaveforms, &uConts, &uEvents, &uComments, &uTrackings, &bAbsolute);
  
  if (bActive)
  {
    std::cout << "WARNING: Trial already active (continuous buffers: " << uConts << 
                 ", events: " << uEvents << "). Using existing configuration." << std::endl;
    log_message(rust_processor, "C++: Using existing trial configuration to avoid conflicts");
  }
  else
  {
    // Only configure trial if none exists
    std::cout << "No active trial detected. Setting up new trial configuration..." << std::endl;
    res = cbSdkSetTrialConfig(0, 1, 0, 0, 0, 0, 0, 0, false, 0, buffer_size, 0, 0, 0, true);
    if (res != CBSDKRESULT_SUCCESS)
    {
      std::cerr << "ERROR: cbSdkSetTrialConfig failed (code " << res << ")" << std::endl;
      delete_signal_processor(rust_processor);
      cbSdkClose(0);
      return 1;
    }
    g_trial_configured = true;
    log_message(rust_processor, "C++: New trial configured");
  }

  // ── Spin-up processing thread ────────────────────────────
  std::thread processing_thread(process_buffer_loop, rust_processor, run_chunk, log_message);

  // ── Allow hardware to start streaming ────────────────────
  std::cout << "Waiting " << WAIT_LENGTH_MS << "ms for data to stabilize..." << std::endl;
  Sleep(WAIT_LENGTH_MS);

  // ── Allocate trial buffers ───────────────────────────────
  cbSdkTrialCont trial;
  for (int i = 0; i < cbNUM_ANALOG_CHANS; ++i)
  {
    trial.samples[i] = malloc(buffer_size * sizeof(INT16));
  }
  res = cbSdkInitTrialData(0, 1, NULL, &trial, NULL, NULL);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cerr << "ERROR: cbSdkInitTrialData failed (code " << res << ")" << std::endl;
    stop_processing = true;
    buffer_cv.notify_all();
    processing_thread.join();
    delete_signal_processor(rust_processor);
    cbSdkClose(0);
    return 1;
  }

  // Debug: Print trial information
  std::cout << "Trial initialized - Channel count: " << trial.count << std::endl;
  for (int i = 0; i < trial.count && i < 5; i++) // Print first 5 channels max
  {
    std::cout << "  Channel " << trial.chan[i] << " sample rate: " << trial.sample_rates[i] << " Hz" << std::endl;
  }

  // ── Main acquisition loop – runs until CTRL+C ────────────
  log_message(rust_processor, "C++: Entering main acquisition loop (press CTRL+C to quit)");
  int no_data_count = 0;
  const int MAX_NO_DATA_WARNINGS = 10;
  
  while (!stop_processing)
  {
    res = cbSdkGetTrialData(0, 1, NULL, &trial, NULL, NULL);
    if (res == CBSDKRESULT_SUCCESS && trial.count > 0)
    {
      no_data_count = 0; // Reset counter on successful data
      INT16 *int_samples = reinterpret_cast<INT16 *>(trial.samples[0]);
      size_t total_samples = trial.num_samples[0];
      size_t processed = 0;
      
      while (processed < total_samples && !stop_processing)
      {
        size_t remaining = total_samples - processed;
        size_t chunk_size = std::min(buffer_size, remaining);

        // FIXED: Better buffer synchronization
        {
          std::unique_lock<std::mutex> lock(buffer_mutex);
          buffer_cv.wait(lock, [&]()
                         { return !buffers[filling_buffer_index].ready || stop_processing; });
          if (stop_processing)
            break;
        }

        for (size_t i = 0; i < chunk_size; ++i)
        {
          buffers[filling_buffer_index].data[i] = static_cast<double>(int_samples[processed + i]) * 0.25; // ↦ µV
        }

        // FIXED: Atomic buffer state change
        {
          std::lock_guard<std::mutex> lock(buffer_mutex);
          buffers[filling_buffer_index].ready = true;
          filling_buffer_index = (filling_buffer_index + 1) % num_buffers;
        }
        buffer_cv.notify_one();

        processed += chunk_size;
      }
    }
    else
    {
      no_data_count++;
      if (no_data_count <= MAX_NO_DATA_WARNINGS)
      {
        if (res != CBSDKRESULT_SUCCESS)
        {
          std::cerr << "cbSdkGetTrialData failed (code " << res << ")" << std::endl;
        }
        else
        {
          std::cerr << "No trial data available (trial.count = " << trial.count << ")" << std::endl;
        }
        
        if (no_data_count == MAX_NO_DATA_WARNINGS)
        {
          std::cerr << "Suppressing further 'no data' warnings..." << std::endl;
        }
      }
    }
    Sleep(50); // Reduced sleep for better responsiveness
  }

  // ── Cleanup ──────────────────────────────────────────────
  log_message(rust_processor, "C++: Shutting down gracefully");
  
  // FIXED: No channel configuration restoration to avoid conflicts
  std::cout << "Performing graceful shutdown without modifying channel configuration..." << std::endl;
  
  for (int i = 0; i < cbNUM_ANALOG_CHANS; ++i)
  {
    free(trial.samples[i]);
  }
  processing_thread.join();
  delete_signal_processor(rust_processor);
  
  // Close CBSDK connection (only once)
  res = cbSdkClose(0);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cerr << "WARNING: cbSdkClose failed (code " << res << ")" << std::endl;
  }
  
  FreeLibrary(hinstLib);

  std::cout << "Shutdown complete. Bye!" << std::endl;
  return 0;
}