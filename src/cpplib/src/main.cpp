#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include "cbsdk.h"
#include <iostream>
#include <string>
#include <chrono>
#include <thread>
#include <future>
#include <vector>
#include <algorithm>
#include <sstream>
#include <mmsystem.h>

// Custom headers
#include "logger.h"
#include "config_reader.h"
#include "data_logger.h"
#include "buffer_manager.h"

// ──────────────────────────────────────────────────────────────
//                        Rust FFI declarations
// ──────────────────────────────────────────────────────────────
typedef void *(__cdecl *CreateSignalProcessorFromConfigFunc)(const char *config_path);
typedef void(__cdecl *DeleteSignalProcessorFunc)(void *processor);
typedef void *(__cdecl *RunChunkFunc)(void *processor, const double *data, size_t length);
typedef void(__cdecl *LogMessageFunc)(void *processor, const char *message);

// ──────────────────────────────────────────────────────────────
//                         Global state
// ──────────────────────────────────────────────────────────────
BufferManager *g_buffer_manager = nullptr;
DataLogger *g_data_logger = nullptr;

// ──────────────────────────────────────────────────────────────
//                     Ctrl+C Handler
// ──────────────────────────────────────────────────────────────
BOOL WINAPI ConsoleHandler(DWORD signal)
{
  if (signal == CTRL_C_EVENT)
  {
    Logger::info("Main", "CTRL+C received - initiating graceful shutdown");

    if (g_buffer_manager)
    {
      g_buffer_manager->stop();
    }
    if (g_data_logger)
    {
      g_data_logger->stop();
    }

    return TRUE;
  }
  return FALSE;
}

// ──────────────────────────────────────────────────────────────
//                     Audio Stimulation
// ──────────────────────────────────────────────────────────────
std::string format_time_with_ms(const std::chrono::system_clock::time_point &time_point)
{
  std::time_t time_t = std::chrono::system_clock::to_time_t(time_point);
  char time_str[100];
  std::strftime(time_str, sizeof(time_str), "%Y-%m-%d %H:%M:%S", std::localtime(&time_t));
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                time_point.time_since_epoch()) %
            1000;
  std::ostringstream oss;
  oss << time_str << '.' << std::setfill('0') << std::setw(3) << ms.count();
  return oss.str();
}

void play_audio_pulse()
{
  auto now = std::chrono::system_clock::now();
  Logger::info("Audio", "Playing pulse at: " + format_time_with_ms(now));
  const char *sound_file = "./pink_noise_short.wav";
  PlaySoundA(sound_file, NULL, SND_FILENAME | SND_ASYNC);
}

void schedule_audio_pulse(double timestamp)
{
  auto now = std::chrono::system_clock::now();
  auto target_time = std::chrono::system_clock::from_time_t(static_cast<time_t>(timestamp)) +
                     std::chrono::milliseconds(static_cast<int>((timestamp - static_cast<time_t>(timestamp)) * 1000));

  if (target_time <= now)
  {
    Logger::warn("Audio", "Scheduled time already passed - skipping pulse");
    return;
  }

  auto delay_ms = std::chrono::duration_cast<std::chrono::milliseconds>(target_time - now).count();
  Logger::info("Audio", "Scheduling pulse in " + std::to_string(delay_ms) + " ms");

  static std::mutex futures_mutex;
  static std::vector<std::future<void>> futures;
  std::lock_guard<std::mutex> lock(futures_mutex);
  futures.push_back(std::async(std::launch::async, [target_time]()
                               {
        std::this_thread::sleep_until(target_time);
        play_audio_pulse(); }));

  // Clean up completed futures
  futures.erase(std::remove_if(futures.begin(), futures.end(), [](std::future<void> &f)
                               { return f.wait_for(std::chrono::seconds(0)) == std::future_status::ready; }),
                futures.end());
}

// ──────────────────────────────────────────────────────────────
//                     Signal Processing Thread
// ──────────────────────────────────────────────────────────────
void process_buffer_loop(void *rust_processor, RunChunkFunc run_chunk,
                         LogMessageFunc log_message, BufferManager &buffer_mgr)
{
  Logger::info("Processing", "Processing thread started");

  while (!buffer_mgr.is_stopped())
  {
    size_t buffer_index;
    if (!buffer_mgr.get_ready_buffer(buffer_index))
    {
      break;
    }

    auto start_time = std::chrono::high_resolution_clock::now();
    void *result = run_chunk(rust_processor, buffer_mgr.get_buffer_data(buffer_index), BUFFER_SIZE);
    auto end_time = std::chrono::high_resolution_clock::now();
    auto processing_time = std::chrono::duration_cast<std::chrono::milliseconds>(
                               end_time - start_time)
                               .count();

    if (result != nullptr)
    {
      double timestamp = *reinterpret_cast<double *>(result);
      Logger::debug("Processing", "Chunk processed in " + std::to_string(processing_time) + " ms");

      std::ostringstream msg;
      msg << "Trigger at " << timestamp << " (processing " << processing_time << " ms)";
      log_message(rust_processor, msg.str().c_str());

      schedule_audio_pulse(timestamp);
      delete static_cast<double *>(result);
    }

    buffer_mgr.release_buffer();
  }

  Logger::info("Processing", "Processing thread stopped");
}

// ──────────────────────────────────────────────────────────────
//                     Rust DLL Loading
// ──────────────────────────────────────────────────────────────
bool load_rust_functions(HINSTANCE &hinstLib,
                         CreateSignalProcessorFromConfigFunc &create_signal_processor_from_config,
                         DeleteSignalProcessorFunc &delete_signal_processor,
                         RunChunkFunc &run_chunk,
                         LogMessageFunc &log_message)
{
  Logger::info("Main", "Loading Rust DLL: direct_neural_biasing.dll");

  hinstLib = LoadLibrary(TEXT("./direct_neural_biasing.dll"));
  Sleep(1000); // Allow Windows to finish loading symbols

  if (!hinstLib)
  {
    Logger::error("Main", "Failed to load Rust DLL");
    return false;
  }

  create_signal_processor_from_config = (CreateSignalProcessorFromConfigFunc)
      GetProcAddress(hinstLib, "create_signal_processor_from_config");
  delete_signal_processor = (DeleteSignalProcessorFunc)
      GetProcAddress(hinstLib, "delete_signal_processor");
  run_chunk = (RunChunkFunc)GetProcAddress(hinstLib, "run_chunk");
  log_message = (LogMessageFunc)GetProcAddress(hinstLib, "log_message");

  if (!create_signal_processor_from_config || !delete_signal_processor ||
      !run_chunk || !log_message)
  {
    Logger::error("Main", "Failed to resolve Rust function exports");
    FreeLibrary(hinstLib);
    return false;
  }

  Logger::info("Main", "Rust DLL loaded successfully");
  return true;
}

// ──────────────────────────────────────────────────────────────
//                     Blackrock CBSDK Setup
// ──────────────────────────────────────────────────────────────
bool open_cbsdk_connection(cbSdkConnectionType &connection_type)
{
  Logger::info("CBSDK", "Attempting UDP connection (multi-app safe)");
  cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_UDP);

  if (res != CBSDKRESULT_SUCCESS)
  {
    Logger::warn("CBSDK", "UDP failed (code " + std::to_string(res) + "), trying Central");
    res = cbSdkOpen(0, CBSDKCONNECTION_CENTRAL);

    if (res != CBSDKRESULT_SUCCESS)
    {
      Logger::error("CBSDK", "All connection attempts failed (code " + std::to_string(res) + ")");
      return false;
    }
  }

  // Report actual connection type
  cbSdkInstrumentType instType;
  cbSdkGetType(0, &connection_type, &instType);
  std::string conn_str = (connection_type == CBSDKCONNECTION_CENTRAL ? "Central" : connection_type == CBSDKCONNECTION_UDP ? "UDP"
                                                                                                                          : "Unknown");
  Logger::info("CBSDK", "Connected via: " + conn_str);

  return true;
}

bool setup_trial_config()
{
  Logger::info("CBSDK", "Checking trial configuration");

  uint32_t bActive = 0;
  cbSdkResult res = cbSdkGetTrialConfig(0, &bActive);

  if (bActive)
  {
    Logger::info("CBSDK", "Trial already active - using existing configuration (non-invasive)");
    return true;
  }

  Logger::info("CBSDK", "No active trial - creating new trial configuration");
  res = cbSdkSetTrialConfig(0, 1, 0, 0, 0, 0, 0, 0, false, 0, BUFFER_SIZE, 0, 0, 0, true);

  if (res != CBSDKRESULT_SUCCESS)
  {
    Logger::error("CBSDK", "Failed to configure trial (code " + std::to_string(res) + ")");
    return false;
  }

  Logger::info("CBSDK", "Trial configured successfully");
  return true;
}

// ──────────────────────────────────────────────────────────────
//                            main()
// ──────────────────────────────────────────────────────────────
int main(int argc, char *argv[])
{
  // Initialize logging with timestamp
  Logger::init();
  Logger::info("Main", "===== Application Starting =====");

  // Set up Ctrl+C handler
  SetConsoleCtrlHandler(ConsoleHandler, TRUE);

  // ── Load configuration ─────────────────────────────────────
  const char *config_path = "./config.yaml";
  int channel = ConfigReader::get_channel(config_path);
  if (channel <= 0)
  {
    Logger::warn("Main", "Using fallback channel 65");
    channel = 65;
  }

  bool save_raw_data = ConfigReader::get_save_raw_data(config_path);

  // ── Load Rust DLL ─────────────────────────────────────────
  HINSTANCE hinstLib;
  CreateSignalProcessorFromConfigFunc create_signal_processor_from_config;
  DeleteSignalProcessorFunc delete_signal_processor;
  RunChunkFunc run_chunk;
  LogMessageFunc log_message;

  if (!load_rust_functions(hinstLib, create_signal_processor_from_config,
                           delete_signal_processor, run_chunk, log_message))
  {
    Logger::error("Main", "Fatal: Could not load Rust functions");
    return 1;
  }

  // ── Open CBSDK connection ──────────────────────────────────
  cbSdkConnectionType connection_type;
  if (!open_cbsdk_connection(connection_type))
  {
    Logger::error("Main", "Fatal: Could not establish CBSDK connection");
    FreeLibrary(hinstLib);
    return 1;
  }

  // ── Create signal processor ────────────────────────────────
  void *rust_processor = create_signal_processor_from_config(config_path);
  if (!rust_processor)
  {
    Logger::error("Main", "Fatal: Could not create signal processor");
    cbSdkClose(0);
    FreeLibrary(hinstLib);
    return 1;
  }
  log_message(rust_processor, "Signal processor created from config");

  // ── Verify channel configuration ───────────────────────────
  cbPKT_CHANINFO chan_info;

  // if (chan_info.smpgroup == 0)
  // {
  //   Logger::error("CBSDK", "Channel " + std::to_string(channel) +
  //                              " appears to be disabled (smpgroup=0). Configure the channel in nPlay/Central before running.");
  //   return 1;
  // }

  cbSdkResult res = cbSdkGetChannelConfig(0, channel, &chan_info);
  if (res != CBSDKRESULT_SUCCESS)
  {
    Logger::error("CBSDK", "Channel " + std::to_string(channel) +
                               " not available (code " + std::to_string(res) + ")");
    delete_signal_processor(rust_processor);
    cbSdkClose(0);
    FreeLibrary(hinstLib);
    return 1;
  }

  Logger::info("CBSDK", "Channel " + std::to_string(channel) +
                            " configuration: smpgroup=" + std::to_string(chan_info.smpgroup) +
                            ", ainpopts=" + std::to_string(chan_info.ainpopts) + " (non-invasive mode)");

  // ── Setup trial configuration ──────────────────────────────
  if (!setup_trial_config())
  {
    Logger::error("Main", "Fatal: Could not configure trial");
    delete_signal_processor(rust_processor);
    cbSdkClose(0);
    FreeLibrary(hinstLib);
    return 1;
  }

  // ── Initialize buffer manager ──────────────────────────────
  BufferManager buffer_mgr;
  g_buffer_manager = &buffer_mgr;

  // ── Initialize data logger ─────────────────────────────────
  DataLogger data_logger;
  data_logger.set_enabled(save_raw_data);
  g_data_logger = &data_logger;

  if (save_raw_data)
  {
    data_logger.start(channel);
  }

  // ── Start processing thread ────────────────────────────────
  std::thread processing_thread(process_buffer_loop, rust_processor, run_chunk,
                                log_message, std::ref(buffer_mgr));

  // ── Wait for hardware to stabilize ─────────────────────────
  Logger::info("Main", "Waiting 100ms for hardware to stabilize");
  Sleep(100);

  // ── Allocate trial buffers ─────────────────────────────────
  Logger::info("CBSDK", "Allocating trial buffers");
  cbSdkTrialCont trial;
  for (int i = 0; i < cbNUM_ANALOG_CHANS; ++i)
  {
    trial.samples[i] = malloc(BUFFER_SIZE * sizeof(INT16));
  }

  res = cbSdkInitTrialData(0, 1, NULL, &trial, NULL, NULL);
  if (res != CBSDKRESULT_SUCCESS)
  {
    Logger::error("CBSDK", "Failed to initialize trial data (code " + std::to_string(res) + ")");
    buffer_mgr.stop();
    processing_thread.join();
    data_logger.stop();
    delete_signal_processor(rust_processor);
    cbSdkClose(0);
    FreeLibrary(hinstLib);
    return 1;
  }

  Logger::info("CBSDK", "Trial buffers allocated successfully");

  // ── Main acquisition loop ──────────────────────────────────
  Logger::info("Main", "===== Entering Main Acquisition Loop =====");
  Logger::info("Main", "Press CTRL+C to stop");

  size_t total_chunks_processed = 0;
  size_t no_data_count = 0;
  const size_t MAX_NO_DATA_WARNINGS = 10;

  while (!buffer_mgr.is_stopped())
  {
    res = cbSdkGetTrialData(0, 1, NULL, &trial, NULL, NULL);

    if (res == CBSDKRESULT_SUCCESS && trial.count > 0)
    {
      no_data_count = 0; // Reset on successful data retrieval

      INT16 *int_samples = reinterpret_cast<INT16 *>(trial.samples[0]);
      size_t total_samples = trial.num_samples[0];
      size_t processed = 0;

      while (processed < total_samples && !buffer_mgr.is_stopped())
      {
        size_t remaining = total_samples - processed;
        size_t chunk_size = std::min(BUFFER_SIZE, remaining);

        // Convert INT16 to double (µV)
        double temp_buffer[BUFFER_SIZE];
        for (size_t i = 0; i < chunk_size; ++i)
        {
          temp_buffer[i] = static_cast<double>(int_samples[processed + i]) * 0.25;
        }

        // Log raw data if enabled
        data_logger.log_chunk(temp_buffer, chunk_size);

        // Fill buffer for processing
        if (!buffer_mgr.fill_buffer(temp_buffer, chunk_size))
        {
          break;
        }

        processed += chunk_size;
        total_chunks_processed++;

        if (total_chunks_processed % 1000 == 0)
        {
          Logger::debug("Main", "Processed " + std::to_string(total_chunks_processed) + " chunks");
        }
      }
    }
    else
    {
      no_data_count++;
      if (no_data_count <= MAX_NO_DATA_WARNINGS)
      {
        if (res != CBSDKRESULT_SUCCESS)
        {
          Logger::warn("CBSDK", "cbSdkGetTrialData failed (code " + std::to_string(res) + ")");
        }
        else
        {
          Logger::warn("CBSDK", "No trial data available (count=" + std::to_string(trial.count) + ")");
        }

        if (no_data_count == MAX_NO_DATA_WARNINGS)
        {
          Logger::info("CBSDK", "Suppressing further 'no data' warnings");
        }
      }
    }

    Sleep(50); // Brief sleep to prevent CPU spinning
  }

  // ── Cleanup ────────────────────────────────────────────────
  Logger::info("Main", "===== Beginning Shutdown Sequence =====");
  Logger::info("Main", "Total chunks processed: " + std::to_string(total_chunks_processed));

  // Stop data logging
  data_logger.stop();

  // Free trial buffers
  Logger::debug("Main", "Freeing trial buffers");
  for (int i = 0; i < cbNUM_ANALOG_CHANS; ++i)
  {
    free(trial.samples[i]);
  }

  // Wait for processing thread
  Logger::debug("Main", "Waiting for processing thread to complete");
  processing_thread.join();

  // Cleanup Rust processor
  Logger::debug("Main", "Cleaning up Rust signal processor");
  delete_signal_processor(rust_processor);

  // Close CBSDK
  Logger::info("CBSDK", "Closing connection");
  res = cbSdkClose(0);
  if (res != CBSDKRESULT_SUCCESS)
  {
    Logger::warn("CBSDK", "Close returned error code " + std::to_string(res));
  }

  // Unload DLL
  Logger::debug("Main", "Unloading Rust DLL");
  FreeLibrary(hinstLib);

  Logger::info("Main", "===== Shutdown Complete =====");
  Logger::close();

  std::cout << "\nShutdown complete. Bye!" << std::endl;
  return 0;
}