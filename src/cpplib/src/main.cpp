#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include "cbsdk.h"
#include <iostream>
#include <string>
#include <chrono>
#include <thread>
#include <future>
#include <cstring>
#include <mmsystem.h>
#include <iomanip>
#include <sstream>

// Custom headers
#include "config_reader.h"

using namespace std;

// ──────────────────────────────────────────────────────────────
//                        Rust FFI declarations
// ──────────────────────────────────────────────────────────────
typedef void *(__cdecl *CreateSignalProcessorFromConfigFunc)(const char *config_path);
typedef void(__cdecl *DeleteSignalProcessorFunc)(void *processor);
typedef void *(__cdecl *RunChunkFunc)(void *processor, const double *data, size_t length);
typedef void(__cdecl *LogMessageFunc)(void *processor, const char *message);

// ──────────────────────────────────────────────────────────────
//                     Global state for clean shutdown
// ──────────────────────────────────────────────────────────────
volatile bool g_running = true;

// ──────────────────────────────────────────────────────────────
//                     Ctrl+C Handler
// ──────────────────────────────────────────────────────────────
BOOL WINAPI ConsoleHandler(DWORD signal)
{
  if (signal == CTRL_C_EVENT)
  {
    cout << "\nCTRL+C received - initiating graceful shutdown..." << endl;
    g_running = false;
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
//                            main()
// ──────────────────────────────────────────────────────────────
int main(int argc, char *argv[])
{
  cout << "===== Direct Neural Biasing - Starting =====" << endl;

  // Set up Ctrl+C handler
  SetConsoleCtrlHandler(ConsoleHandler, TRUE);

  // ── Configuration ─────────────────────────────────────────
  const char *config_path = "./config.yaml";
  int channel = ConfigReader::get_channel(config_path);

  if (argc > 1)
  {
    channel = atoi(argv[1]);
  }
  cout << "Using channel: " << channel << endl;

  int sleep_ms = ConfigReader::get_setup_sleep_ms("./config.yaml");

  if (sleep_ms == -1)
  {
    // Handle error - maybe use a default value
    sleep_ms = 1000; // Default to 1 second
    Logger::warn("Main", "Using default setup_sleep_ms: 1000ms");
  }

  // ── Load Rust DLL ─────────────────────────────────────────
  cout << "Loading Rust DLL..." << endl;
  HINSTANCE hinstLib = LoadLibrary(TEXT("./direct_neural_biasing.dll"));
  if (!hinstLib)
  {
    cerr << "ERROR: Failed to load Rust DLL" << endl;
    return 1;
  }

  // Get function pointers
  auto create_signal_processor_from_config = (CreateSignalProcessorFromConfigFunc)
      GetProcAddress(hinstLib, "create_signal_processor_from_config");
  auto delete_signal_processor = (DeleteSignalProcessorFunc)
      GetProcAddress(hinstLib, "delete_signal_processor");
  auto run_chunk = (RunChunkFunc)GetProcAddress(hinstLib, "run_chunk");
  auto log_message = (LogMessageFunc)GetProcAddress(hinstLib, "log_message");

  if (!create_signal_processor_from_config || !delete_signal_processor ||
      !run_chunk || !log_message)
  {
    cerr << "ERROR: Failed to resolve Rust function exports" << endl;
    FreeLibrary(hinstLib);
    return 1;
  }
  cout << "Rust DLL loaded successfully" << endl;

  // ── Create signal processor ────────────────────────────────
  void *rust_processor = create_signal_processor_from_config(config_path);
  if (!rust_processor)
  {
    cerr << "ERROR: Could not create signal processor" << endl;
    FreeLibrary(hinstLib);
    return 1;
  }
  log_message(rust_processor, "Signal processor created from config");

  // ── Open CBSDK connection ──────────────────────────────────
  cout << "Opening CBSDK connection..." << endl;
  cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_DEFAULT);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cerr << "ERROR: cbSdkOpen failed with code: " << res << endl;
    delete_signal_processor(rust_processor);
    FreeLibrary(hinstLib);
    return 1;
  }

  // Give the system time to initialize
  this_thread::sleep_for(chrono::milliseconds(sleep_ms));

  // ── Setup channel (using our reliable code) ───────────────
  cbPKT_CHANINFO chan_info;
  memset(&chan_info, 0, sizeof(cbPKT_CHANINFO));

  // Get current channel configuration
  res = cbSdkGetChannelConfig(0, channel, &chan_info);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cerr << "ERROR: cbSdkGetChannelConfig failed with code: " << res << endl;
    cbSdkClose(0);
    delete_signal_processor(rust_processor);
    FreeLibrary(hinstLib);
    return 1;
  }

  // Give hardware time to apply settings
  this_thread::sleep_for(chrono::milliseconds(sleep_ms));

  // Check if channel exists and supports analog input
  if (!(chan_info.chancaps & cbCHAN_EXISTS))
  {
    cerr << "ERROR: Channel " << channel << " does not exist" << endl;
    cbSdkClose(0);
    delete_signal_processor(rust_processor);
    FreeLibrary(hinstLib);
    return 1;
  }

  if (!(chan_info.chancaps & cbCHAN_AINP))
  {
    cerr << "ERROR: Channel " << channel << " does not support analog input" << endl;
    cbSdkClose(0);
    delete_signal_processor(rust_processor);
    FreeLibrary(hinstLib);
    return 1;
  }

  cout << "Channel " << channel << " is configured with sample group: "
       << chan_info.smpgroup << endl;

  // ── Setup trial configuration ──────────────────────────────
  res = cbSdkSetTrialConfig(0, 1, 0, 0, 0, 0, 0, 0, false,
                            0, cbSdk_CONTINUOUS_DATA_SAMPLES, 0, 0, 0, true);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cerr << "ERROR: cbSdkSetTrialConfig failed with code: " << res << endl;
    cbSdkClose(0);
    delete_signal_processor(rust_processor);
    FreeLibrary(hinstLib);
    return 1;
  }

  // Create trial structure
  cbSdkTrialCont trial;
  memset(&trial, 0, sizeof(cbSdkTrialCont));

  // Allocate memory for samples
  for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
  {
    trial.samples[i] = calloc(cbSdk_CONTINUOUS_DATA_SAMPLES, sizeof(INT16));
    if (!trial.samples[i])
    {
      cerr << "ERROR: Memory allocation failed" << endl;
      // Clean up
      for (int j = 0; j < i; j++)
        free(trial.samples[j]);
      cbSdkClose(0);
      delete_signal_processor(rust_processor);
      FreeLibrary(hinstLib);
      return 1;
    }
  }

  // Initialize trial data
  res = cbSdkInitTrialData(0, 1, NULL, &trial, NULL, NULL);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cerr << "ERROR: cbSdkInitTrialData failed with code: " << res << endl;
    for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
      free(trial.samples[i]);
    cbSdkClose(0);
    delete_signal_processor(rust_processor);
    FreeLibrary(hinstLib);
    return 1;
  }

  // Give system time to start streaming
  this_thread::sleep_for(chrono::milliseconds(sleep_ms));

  // ── Main acquisition loop ──────────────────────────────────
  cout << "\n===== Starting data acquisition =====" << endl;
  cout << "Press CTRL+C to stop\n"
       << endl;

  // Prepare conversion buffer
  double *conversion_buffer = new double[cbSdk_CONTINUOUS_DATA_SAMPLES];

  size_t total_samples = 0;
  size_t chunks_processed = 0;
  int channel_index = -1;

  while (g_running)
  {
    // Get trial data
    res = cbSdkGetTrialData(0, 1, NULL, &trial, NULL, NULL);

    if (res == CBSDKRESULT_SUCCESS && trial.count > 0)
    {
      // Find our channel in the trial data
      channel_index = -1;
      for (int i = 0; i < trial.count; i++)
      {
        if (trial.chan[i] == channel)
        {
          channel_index = i;
          break;
        }
      }

      if (channel_index >= 0 && trial.num_samples[channel_index] > 0)
      {
        size_t num_samples = trial.num_samples[channel_index];
        INT16 *raw_samples = (INT16 *)trial.samples[channel_index];

        // Convert INT16 to double (in microvolts)
        // The 0.25 conversion factor is standard for Blackrock
        for (size_t i = 0; i < num_samples; i++)
        {
          conversion_buffer[i] = static_cast<double>(raw_samples[i]) * 0.25;
        }

        // Send to Rust for processing
        void *result = run_chunk(rust_processor, conversion_buffer, num_samples);

        if (result != nullptr)
        {
          // Rust returned a timestamp - trigger detected!
          double timestamp = *reinterpret_cast<double *>(result);

          cout << "[TRIGGER] Detected at timestamp: " << fixed
               << setprecision(3) << timestamp << endl;

          // Log to Rust
          ostringstream msg;
          msg << "Trigger detected at " << timestamp;
          log_message(rust_processor, msg.str().c_str());

          // Schedule audio pulse
          schedule_audio_pulse(timestamp);

          // Clean up the result
          delete static_cast<double *>(result);
        }

        total_samples += num_samples;
        chunks_processed++;

        // Status update every second (approximately)
        if (chunks_processed % 300 == 0) // 30kHz / 100 samples per chunk ≈ 300 chunks/sec
        {
          cout << "[STATUS] Processed " << total_samples << " samples ("
               << chunks_processed << " chunks)" << endl;
        }
      }
    }
    else if (res != CBSDKRESULT_SUCCESS)
    {
      cerr << "WARNING: cbSdkGetTrialData failed with code: " << res << endl;
    }

    // Small sleep to prevent CPU spinning
    Sleep(10);
  }

  // ── Cleanup ────────────────────────────────────────────────
  cout << "\n===== Shutting down =====" << endl;
  cout << "Total samples processed: " << total_samples << endl;

  // Free conversion buffer
  delete[] conversion_buffer;

  // Free trial memory
  for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
  {
    if (trial.samples[i])
      free(trial.samples[i]);
  }

  // Clean up Rust processor
  log_message(rust_processor, "Shutting down signal processor");
  delete_signal_processor(rust_processor);

  // Close CBSDK
  res = cbSdkClose(0);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cerr << "WARNING: cbSdkClose returned error code: " << res << endl;
  }

  // Unload DLL
  FreeLibrary(hinstLib);

  cout << "Shutdown complete. Goodbye!" << endl;
  return 0;
}