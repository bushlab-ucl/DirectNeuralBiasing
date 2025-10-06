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
const int WAIT_LENGTH_MS = 100;  // Fixed wait time before first data pull

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
//                      Data Logging System (Queue-Based)
// ──────────────────────────────────────────────────────────────
struct LogChunk
{
  std::vector<double> data;
};

std::queue<LogChunk> log_queue;
std::mutex log_queue_mutex;
std::condition_variable log_queue_cv;
bool stop_logging = false;
bool enable_logging = false;
const size_t MAX_QUEUE_SIZE = 1000; // ~4MB of buffering (1000 chunks * 4096 samples * 8 bytes / chunk)

// Background thread for writing data to file
void data_logging_thread(const std::string &filename)
{
  std::ofstream outfile(filename, std::ios::binary);
  if (!outfile.is_open())
  {
    std::cerr << "ERROR: Failed to open log file: " << filename << std::endl;
    stop_logging = true;
    return;
  }

  std::cout << "Data logging started: " << filename << std::endl;

  size_t total_samples_written = 0;
  size_t chunks_written = 0;

  while (true)
  {
    LogChunk chunk;

    // Wait for data in the queue
    {
      std::unique_lock<std::mutex> lock(log_queue_mutex);
      log_queue_cv.wait(lock, []()
                        { return stop_logging || !log_queue.empty(); });

      // Process remaining queue items even after stop signal
      if (log_queue.empty())
      {
        if (stop_logging)
          break;
        else
          continue;
      }

      // Get the next chunk from queue
      chunk = std::move(log_queue.front());
      log_queue.pop();

      // Notify if we were blocking due to full queue
      if (log_queue.size() < MAX_QUEUE_SIZE)
      {
        log_queue_cv.notify_all();
      }
    }

    // Write to file (outside the lock for performance)
    if (!chunk.data.empty())
    {
      outfile.write(reinterpret_cast<const char *>(chunk.data.data()),
                    chunk.data.size() * sizeof(double));
      total_samples_written += chunk.data.size();
      chunks_written++;

      // Periodic progress report
      if (chunks_written % 1000 == 0)
      {
        std::cout << "Logged " << chunks_written << " chunks ("
                  << (total_samples_written / 30000.0) << " seconds of data)" << std::endl;
      }
    }
  }

  outfile.close();
  std::cout << "Data logging stopped. Total samples written: " << total_samples_written
            << " (" << (total_samples_written / 30000.0) << " seconds)" << std::endl;
}

// Add data to logging queue (with backpressure handling)
void log_data_chunk(const double *data, size_t length)
{
  if (!enable_logging)
    return;

  std::unique_lock<std::mutex> lock(log_queue_mutex);

  // Wait if queue is full (applies backpressure to acquisition)
  if (log_queue.size() >= MAX_QUEUE_SIZE)
  {
    static bool warned = false;
    if (!warned)
    {
      std::cerr << "WARNING: Log queue full (" << MAX_QUEUE_SIZE
                << " chunks). Waiting for disk I/O to catch up..." << std::endl;
      std::cerr << "This will slow down real-time acquisition. Consider using a faster disk." << std::endl;
      warned = true;
    }

    // Wait for queue to have space (with timeout to check stop flag)
    log_queue_cv.wait_for(lock, std::chrono::milliseconds(100), []()
                          { return log_queue.size() < MAX_QUEUE_SIZE || stop_logging; });

    if (stop_logging)
      return;
  }

  // Create new chunk and copy data
  LogChunk chunk;
  chunk.data.assign(data, data + length);
  log_queue.push(std::move(chunk));

  // Notify logging thread
  log_queue_cv.notify_one();
}

// ──────────────────────────────────────────────────────────────
//                 Utility: read config from config.yaml
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

bool get_save_raw_data_from_config(const std::string &config_path)
{
  std::ifstream inFile(config_path);
  if (!inFile.is_open())
  {
    return false;
  }

  std::string line;
  bool in_processor_block = false;
  while (std::getline(inFile, line))
  {
    if (line.find("processor:") != std::string::npos)
    {
      in_processor_block = true;
      continue;
    }
    if (in_processor_block)
    {
      if (line.find(':') != std::string::npos && line.find_first_not_of(" \t") != std::string::npos && line[0] != ' ' && line[0] != '\t')
      {
        break;
      }
      auto pos = line.find("save_raw_data:");
      if (pos != std::string::npos)
      {
        std::string value = line.substr(pos + 14); // 14 = len("save_raw_data:")
        // Trim whitespace
        value.erase(0, value.find_first_not_of(" \t"));
        value.erase(value.find_last_not_of(" \t\r\n") + 1);
        return (value == "true" || value == "True" || value == "TRUE");
      }
    }
  }
  return false;
}

// ──────────────────────────────────────────────────────────────
//                 Windows console Ctrl+C handler
// ──────────────────────────────────────────────────────────────
// Global variables for cleanup
cbPKT_CHANINFO *g_original_chan_info = nullptr;
int g_channel = -1;
bool g_channel_configured = false;

BOOL WINAPI ConsoleHandler(DWORD signal)
{
  if (signal == CTRL_C_EVENT)
  {
    std::cout << "\nCTRL+C received – shutting down…" << std::endl;

    // Restore channel configuration if it was modified
    if (g_channel_configured && g_original_chan_info != nullptr && g_channel > 0)
    {
      std::cout << "Restoring channel configuration due to Ctrl+C..." << std::endl;
      cbSdkResult res = cbSdkSetChannelConfig(0, g_channel, g_original_chan_info);
      if (res != CBSDKRESULT_SUCCESS)
      {
        std::cerr << "WARNING: Failed to restore channel config on Ctrl+C (code " << res << ")" << std::endl;
      }
      else
      {
        std::cout << "Channel configuration restored successfully" << std::endl;
      }

      // Clear any channel masks
      res = cbSdkSetChannelMask(0, g_channel, 0);
      if (res != CBSDKRESULT_SUCCESS)
      {
        std::cerr << "WARNING: Failed to clear channel mask on Ctrl+C (code " << res << ")" << std::endl;
      }
    }

    stop_processing = true;
    stop_logging = true;
    buffer_cv.notify_all();
    log_queue_cv.notify_all();
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

// Generate filename with timestamp in data directory
std::string generate_log_filename(int channel)
{
  // Create data directory if it doesn't exist
  CreateDirectoryA("./data", NULL);

  auto now = std::chrono::system_clock::now();
  std::time_t time_t = std::chrono::system_clock::to_time_t(now);
  char time_str[100];
  std::strftime(time_str, sizeof(time_str), "%Y%m%d_%H%M%S", std::localtime(&time_t));

  std::ostringstream oss;
  oss << "./data/raw_data_ch" << channel << "_" << time_str << ".bin";
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
    {
      std::unique_lock<std::mutex> lock(buffer_mutex);
      buffer_cv.wait(lock, []
                     { return stop_processing || buffers[0].ready || buffers[1].ready; });
      if (stop_processing)
        break;
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

  // ── Read configuration ────────────────────────────────────
  const char *config_path = "./config.yaml";
  int channel = get_channel_from_config(config_path);
  if (channel <= 0)
  {
    std::cerr << "Falling back to channel 65." << std::endl;
    channel = 65;
  }
  std::cout << "Using channel " << channel << " from config.yaml" << std::endl;

  // Check if we should save raw data
  enable_logging = get_save_raw_data_from_config(config_path);
  if (enable_logging)
  {
    std::cout << "Raw data logging ENABLED (queue size: " << MAX_QUEUE_SIZE << " chunks)" << std::endl;
  }
  else
  {
    std::cout << "Raw data logging DISABLED" << std::endl;
  }

  // // ── Open Blackrock CBSDK connection ──────────────────────
  // std::cout << "Attempting to open CBSDK…" << std::endl;
  // cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_DEFAULT);
  // if (res != CBSDKRESULT_SUCCESS)
  // {
  //   std::cerr << "ERROR: cbSdkOpen failed (code " << res << ")" << std::endl;
  //   return 1;
  // }
  // std::cout << "CBSDK opened successfully!" << std::endl;

  // ── Open Blackrock CBSDK connection ──────────────────────
  std::cout << "Attempting to open CBSDK with UDP (multi-app safe)…" << std::endl;
  cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_UDP);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cout << "UDP failed (code " << res << "), trying Central..." << std::endl;
    res = cbSdkOpen(0, CBSDKCONNECTION_CENTRAL);
    if (res != CBSDKRESULT_SUCCESS)
    {
      std::cerr << "ERROR: cbSdkOpen failed (code " << res << ")" << std::endl;
      return 1;
    }
  }

  // ── Print Debug to check connection issues  ──────────────────────
  cbSdkConnectionType conType;
  cbSdkInstrumentType instType;
  cbSdkGetType(0, &conType, &instType);
  std::cout << "Connection type: " << (conType == CBSDKCONNECTION_CENTRAL ? "Central" : conType == CBSDKCONNECTION_UDP ? "UDP"
                                                                                                                       : "Default")
            << std::endl;

  // ── Create Rust signal processor ─────────────────────────
  void *rust_processor = create_signal_processor_from_config(config_path);
  if (!rust_processor)
  {
    std::cerr << "Failed to create Rust signal processor from " << config_path << std::endl;
    return 1;
  }
  log_message(rust_processor, "C++: Signal processor created from config.yaml");

  // // ── Configure Blackrock channel ──────────────────────────
  cbPKT_CHANINFO chan_info;
  // cbSdkGetChannelConfig(0, channel, &chan_info);
  // std::cout << "BEFORE modification - smpgroup: " << chan_info.smpgroup << std::endl;
  // std::cout << "BEFORE modification - ainpopts: " << chan_info.ainpopts << std::endl;

  // res = cbSdkGetChannelConfig(0, channel, &chan_info);
  // if (res != CBSDKRESULT_SUCCESS)
  // {
  //   std::cerr << "ERROR: cbSdkGetChannelConfig (code " << res << ")" << std::endl;
  //   return 1;
  // }

  // // Store original configuration for cleanup (global variables for Ctrl+C handler)
  // g_original_chan_info = new cbPKT_CHANINFO(chan_info);
  // g_channel = channel;

  // // Configure for continuous acquisition
  // chan_info.smpgroup = 5; // Continuous 30 kHz
  // std::cout << "AFTER modification - smpgroup: " << chan_info.smpgroup << std::endl;
  // chan_info.ainpopts = 0;
  // res = cbSdkSetChannelConfig(0, channel, &chan_info);
  // if (res != CBSDKRESULT_SUCCESS)
  // {
  //   std::cerr << "ERROR: cbSdkSetChannelConfig (code " << res << ")" << std::endl;
  //   delete g_original_chan_info;
  //   g_original_chan_info = nullptr;
  //   return 1;
  // }

  // g_channel_configured = true;
  // log_message(rust_processor, "C++: Channel configured for continuous acquisition");

  // Use existing channel configuration without modification
  std::cout << "Using existing channel configuration (smpgroup: " << chan_info.smpgroup << ")" << std::endl;
  log_message(rust_processor, "C++: Using existing channel configuration");

  // No modifications made, so no need to restore anything
  g_channel_configured = false;

  // ── Trial configuration ──────────────────────────────────
  // Check trial status before setting
  uint32_t bActive = 0;
  cbSdkGetTrialConfig(0, &bActive);
  std::cout << "Trial already active: " << (bActive ? "YES" : "NO") << std::endl;
  res = cbSdkSetTrialConfig(0, 1, 0, 0, 0, 0, 0, 0, false, 0, buffer_size, 0, 0, 0, true);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cerr << "ERROR: cbSdkSetTrialConfig (code " << res << ")" << std::endl;
    return 1;
  }
  log_message(rust_processor, "C++: Trial configured");

  // ── Start logging thread if enabled ──────────────────────
  std::thread logging_thread;
  if (enable_logging)
  {
    std::string log_filename = generate_log_filename(channel);
    logging_thread = std::thread(data_logging_thread, log_filename);
    log_message(rust_processor, ("C++: Data logging to " + log_filename).c_str());
  }

  // ── Spin-up processing thread ────────────────────────────
  std::thread processing_thread(process_buffer_loop, rust_processor, run_chunk, log_message);

  // ── Allow hardware to start streaming ────────────────────
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
    std::cerr << "ERROR: cbSdkInitTrialData (code " << res << ")" << std::endl;
    stop_processing = true;
    stop_logging = true;
    buffer_cv.notify_all();
    log_queue_cv.notify_all();
    processing_thread.join();
    if (enable_logging && logging_thread.joinable())
      logging_thread.join();
    return 1;
  }

  // ── Main acquisition loop – runs until CTRL+C ────────────
  log_message(rust_processor, "C++: Entering main acquisition loop (press CTRL+C to quit)");
  while (!stop_processing)
  {
    res = cbSdkGetTrialData(0, 1, NULL, &trial, NULL, NULL);
    if (res == CBSDKRESULT_SUCCESS && trial.count > 0)
    {
      INT16 *int_samples = reinterpret_cast<INT16 *>(trial.samples[0]);
      size_t total_samples = trial.num_samples[0];
      size_t processed = 0;
      while (processed < total_samples)
      {
        size_t remaining = total_samples - processed;
        size_t chunk_size = std::min(buffer_size, remaining);

        {
          std::unique_lock<std::mutex> lock(buffer_mutex);
          buffer_cv.wait(lock, []
                         { return !buffers[filling_buffer_index].ready || stop_processing; });
          if (stop_processing)
            break;
        }

        // Convert to double and fill buffer
        for (size_t i = 0; i < chunk_size; ++i)
        {
          buffers[filling_buffer_index].data[i] = static_cast<double>(int_samples[processed + i]) * 0.25; // ↦ µV
        }

        // Log data if enabled (with backpressure - will wait if disk is slow)
        log_data_chunk(buffers[filling_buffer_index].data, chunk_size);

        {
          std::lock_guard<std::mutex> lock(buffer_mutex);
          buffers[filling_buffer_index].ready = true;
        }
        buffer_cv.notify_one();

        filling_buffer_index = (filling_buffer_index + 1) % num_buffers;
        processed += chunk_size;
      }
    }
    Sleep(100); // Give CPU a small breather
  }

  // ── Cleanup ──────────────────────────────────────────────
  log_message(rust_processor, "C++: Shutting down");

  // Stop logging thread gracefully (flush remaining data)
  if (enable_logging)
  {
    std::cout << "Flushing remaining log data..." << std::endl;
    {
      std::lock_guard<std::mutex> lock(log_queue_mutex);
      std::cout << "Log queue size at shutdown: " << log_queue.size() << " chunks" << std::endl;
    }
    stop_logging = true;
    log_queue_cv.notify_all();
    if (logging_thread.joinable())
      logging_thread.join();
  }

  // Restore original channel configuration to prevent persistent effects
  if (g_channel_configured && g_original_chan_info != nullptr)
  {
    std::cout << "Restoring original channel configuration..." << std::endl;
    res = cbSdkSetChannelConfig(0, g_channel, g_original_chan_info);
    if (res != CBSDKRESULT_SUCCESS)
    {
      std::cerr << "WARNING: Failed to restore channel config (code " << res << ")" << std::endl;
    }
    else
    {
      std::cout << "Channel configuration restored successfully" << std::endl;
    }

    // Clean up global variables
    delete g_original_chan_info;
    g_original_chan_info = nullptr;
    g_channel_configured = false;
  }

  for (int i = 0; i < cbNUM_ANALOG_CHANS; ++i)
  {
    free(trial.samples[i]);
  }
  processing_thread.join();
  delete_signal_processor(rust_processor);
  cbSdkClose(0);
  FreeLibrary(hinstLib);

  std::cout << "Shutdown complete. Bye!" << std::endl;
  return 0;
}