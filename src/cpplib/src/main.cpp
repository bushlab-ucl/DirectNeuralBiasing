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

// Rust FFI declarations
typedef void *(__cdecl *CreateSignalProcessorFromConfigFunc)(const char *config_path);
typedef void(__cdecl *DeleteSignalProcessorFunc)(void *processor);
typedef void *(__cdecl *RunChunkFunc)(void *processor, const double *data, size_t length);

// Constants
const size_t buffer_size = 4096; // Buffer size for real-time processing
const size_t num_buffers = 2;    // Number of reusable buffers (double buffering)

// Buffer struct
struct Buffer
{
  double data[buffer_size];
  bool ready;
};

Buffer buffers[num_buffers];
size_t filling_buffer_index = 0; // Index of the buffer being filled

std::mutex buffer_mutex;
std::condition_variable buffer_cv;
bool stop_processing = false; // Flag to stop the threads

// Function to load Rust functions from DLL
bool load_rust_functions(HINSTANCE &hinstLib,
                         CreateSignalProcessorFromConfigFunc &create_signal_processor_from_config,
                         DeleteSignalProcessorFunc &delete_signal_processor,
                         RunChunkFunc &run_chunk)
{
  hinstLib = LoadLibrary(TEXT("./direct_neural_biasing.dll"));
  Sleep(1000);
  if (hinstLib == NULL)
  {
    std::cerr << "Failed to load Rust DLL!" << std::endl;
    return false;
  }

  create_signal_processor_from_config = (CreateSignalProcessorFromConfigFunc)GetProcAddress(hinstLib, "create_signal_processor_from_config");
  delete_signal_processor = (DeleteSignalProcessorFunc)GetProcAddress(hinstLib, "delete_signal_processor");
  run_chunk = (RunChunkFunc)GetProcAddress(hinstLib, "run_chunk");

  if (create_signal_processor_from_config == NULL || delete_signal_processor == NULL || run_chunk == NULL)
  {
    std::cerr << "Failed to load Rust functions!" << std::endl;
    FreeLibrary(hinstLib);
    return false;
  }

  return true;
}

// Helper function to format time with milliseconds
std::string format_time_with_ms(const std::chrono::system_clock::time_point &time_point)
{
  // Get time_t from time_point
  std::time_t time_t = std::chrono::system_clock::to_time_t(time_point);

  // Format date and time
  char time_str[100];
  std::strftime(time_str, sizeof(time_str), "%Y-%m-%d %H:%M:%S", std::localtime(&time_t));

  // Add milliseconds
  auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                time_point.time_since_epoch()) %
            1000;

  // Combine into a single string
  std::ostringstream oss;
  oss << time_str << "." << std::setfill('0') << std::setw(3) << ms.count();

  return oss.str();
}

// Function to play an audio pulse
void play_audio_pulse()
{
  // Get and display current system time
  auto now = std::chrono::system_clock::now();
  std::cout << "Playing audio pulse at system time: " << format_time_with_ms(now) << std::endl;

  // Specify the path to a .wav file (make sure the file exists in the specified location)
  const char *sound_file = "./pink_noise_short.wav"; // Replace with your .wav file path

  // Play the sound asynchronously (so it doesn't block the main thread)
  PlaySoundA(sound_file, NULL, SND_FILENAME | SND_ASYNC);
}

// Function to schedule audio pulse at a specific timestamp
void schedule_audio_pulse(double timestamp)
{
  // Get current time
  auto now = std::chrono::system_clock::now();
  std::string current_time_str = format_time_with_ms(now);

  // Convert timestamp (UNIX epoch seconds) to system clock time point
  std::chrono::system_clock::time_point target_time =
      std::chrono::system_clock::from_time_t(static_cast<time_t>(timestamp)) +
      std::chrono::milliseconds(static_cast<int>((timestamp - static_cast<time_t>(timestamp)) * 1000));

  std::string target_time_str = format_time_with_ms(target_time);

  // Calculate delay
  auto delay = target_time - now;
  auto delay_ms = std::chrono::duration_cast<std::chrono::milliseconds>(delay).count();

  // If the timestamp is in the past, log and return
  if (delay.count() <= 0)
  {
    std::cout << "Warning: Scheduled time is in the past, not playing audio pulse." << std::endl;
    std::cout << "Current time: " << current_time_str << std::endl;
    std::cout << "Target time: " << target_time_str << " (already passed)" << std::endl;
    return;
  }

  // Print scheduling information
  std::cout << "Current time: " << current_time_str << std::endl;
  std::cout << "Scheduling audio pulse for: " << target_time_str << std::endl;
  std::cout << "Delay: " << delay_ms << " ms" << std::endl;

  // Schedule the audio pulse using async and store the future
  static std::mutex futures_mutex;
  static std::vector<std::future<void>> futures;

  // Create a copy of target_time for the lambda
  auto target_time_copy = target_time;

  // Add the new future with thread-safety
  {
    std::lock_guard<std::mutex> lock(futures_mutex);
    futures.push_back(std::async(std::launch::async, [target_time_copy]()
                                 {
            // Sleep until the target time
            auto sleep_until = target_time_copy;
            std::this_thread::sleep_until(sleep_until);
            
            // Play the sound
            play_audio_pulse(); }));

    // Clean up completed futures to prevent memory growth
    futures.erase(
        std::remove_if(futures.begin(), futures.end(),
                       [](std::future<void> &f)
                       {
                         return f.wait_for(std::chrono::seconds(0)) == std::future_status::ready;
                       }),
        futures.end());
  }
}

// Processing thread function
void process_buffer_loop(void *rust_processor, RunChunkFunc run_chunk)
{
  while (true)
  {
    size_t processing_buffer_index;

    // Wait for a buffer to become ready
    {
      std::unique_lock<std::mutex> lock(buffer_mutex);
      buffer_cv.wait(lock, []
                     { return stop_processing || buffers[0].ready || buffers[1].ready; });

      if (stop_processing)
        break;

      // Find the ready buffer
      processing_buffer_index = buffers[0].ready ? 0 : 1;
      buffers[processing_buffer_index].ready = false; // Mark as being processed
    }

    // Process the buffer
    auto start_time = std::chrono::high_resolution_clock::now();
    void *result = run_chunk(rust_processor, buffers[processing_buffer_index].data, buffer_size);
    auto end_time = std::chrono::high_resolution_clock::now();
    auto processing_time = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();

    // Print the first object from the result
    if (result != nullptr)
    {
      // Rust returned a valid timestamp
      double timestamp = *reinterpret_cast<double *>(result);

      // Log processing information
      std::cout << "Processing time: " << processing_time << " ms" << std::endl;

      // Schedule the audio pulse at the specified timestamp instead of playing immediately
      schedule_audio_pulse(timestamp);

      delete static_cast<double *>(result);
    }

    // Notify the data collection thread
    buffer_cv.notify_one();
  }
}

int main(int argc, char *argv[])
{
  HINSTANCE hinstLib;
  CreateSignalProcessorFromConfigFunc create_signal_processor_from_config;
  DeleteSignalProcessorFunc delete_signal_processor;
  RunChunkFunc run_chunk;

  // Load the Rust library and functions
  if (!load_rust_functions(hinstLib, create_signal_processor_from_config, delete_signal_processor, run_chunk))
  {
    return 1;
  }

  // Initialize Rust Signal Processor from config file
  const char *config_path = "./config.yaml";
  void *rust_processor = create_signal_processor_from_config(config_path);
  if (rust_processor == NULL)
  {
    std::cerr << "Failed to create Rust signal processor from config: " << config_path << std::endl;
    std::cerr << "Make sure the config.yaml file exists in the current directory." << std::endl;
    FreeLibrary(hinstLib);
    return 1;
  }

  std::cout << "Successfully created signal processor from config: " << config_path << std::endl;

  // Start the processing thread
  std::thread processing_thread(process_buffer_loop, rust_processor, run_chunk);

  // Before cbSdkOpen
  std::cout << "Attempting to open CBSDK..." << std::endl;

  // Try opening with different connection types
  cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_DEFAULT);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cerr << "ERROR: cbSdkOpen failed with error code: " << res << std::endl;

    // Try Central
    std::cout << "Trying Central connection..." << std::endl;
    res = cbSdkOpen(0, CBSDKCONNECTION_CENTRAL);
    if (res != CBSDKRESULT_SUCCESS)
    {
      std::cerr << "ERROR: Central connection failed with error code: " << res << std::endl;

      // Try UDP
      std::cout << "Trying UDP connection..." << std::endl;
      res = cbSdkOpen(0, CBSDKCONNECTION_UDP);
      if (res != CBSDKRESULT_SUCCESS)
      {
        std::cerr << "ERROR: UDP connection failed with error code: " << res << std::endl;
        return 1;
      }
    }
  }

  std::cout << "CBSDK opened successfully!" << std::endl;

  // Configure the first channel (continuous recording at 30kHz)
  // NOTE: Channel number and sampling rate now come from config.yaml
  // This assumes channel 1 for now, but could be made configurable
  cbPKT_CHANINFO chan_info;
  res = cbSdkGetChannelConfig(0, 1, &chan_info);
  chan_info.smpgroup = 5; // Continuous sampling at 30kHz
  res = cbSdkSetChannelConfig(0, 1, &chan_info);

  // Set up trial configuration to get continuous data
  res = cbSdkSetTrialConfig(0, 1, 0, 0, 0, 0, 0, 0, false, 0, buffer_size, 0, 0, 0, true);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cerr << "ERROR: cbSdkSetTrialConfig" << std::endl;
    return 1;
  }

  Sleep(1000); // Wait to allow data to start flowing

  // Allocate memory for the trial data
  cbSdkTrialCont trial;
  for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
  {
    trial.samples[i] = malloc(buffer_size * sizeof(INT16));
  }

  // Initialize the trial data structure
  res = cbSdkInitTrialData(0, 1, NULL, &trial, NULL, NULL);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cerr << "ERROR: cbSdkInitTrialData" << std::endl;
    return 1;
  }

  // Main loop to collect data
  while (true)
  {
    // Fetch data from Blackrock
    res = cbSdkGetTrialData(0, 1, NULL, &trial, NULL, NULL);
    if (res == CBSDKRESULT_SUCCESS)
    {
      if (trial.count > 0)
      {
        INT16 *int_samples = reinterpret_cast<INT16 *>(trial.samples[0]);
        size_t total_samples = trial.num_samples[0];
        size_t processed_samples = 0;

        while (processed_samples < total_samples)
        {
          size_t remaining_samples = total_samples - processed_samples;
          size_t chunk_size = std::min(buffer_size, remaining_samples);

          // Ensure we are switching to a buffer that's not "ready"
          {
            std::unique_lock<std::mutex> lock(buffer_mutex);
            buffer_cv.wait(lock, [&]()
                           { return !buffers[filling_buffer_index].ready || stop_processing; });

            if (stop_processing)
              break;
          }

          // Convert INT16 samples to voltage values (microvolts)
          for (size_t i = 0; i < chunk_size; i++)
          {
            // Convert from INT16 to double (microvolts)
            // The factor 0.25 comes from the typical resolution of Blackrock systems
            // You may need to adjust this based on your specific hardware configuration
            buffers[filling_buffer_index].data[i] = static_cast<double>(int_samples[processed_samples + i]) * 0.25;
          }

          // Mark buffer as ready
          {
            std::lock_guard<std::mutex> lock(buffer_mutex);
            buffers[filling_buffer_index].ready = true;
          }
          buffer_cv.notify_one();

          // Switch to the next buffer (round-robin)
          filling_buffer_index = (filling_buffer_index + 1) % num_buffers;
          processed_samples += chunk_size;
        }
      }
      else
      {
        std::cerr << "No trial data available (trial.count = 0)" << std::endl;
      }
    }
    else
    {
      std::cerr << "Error fetching trial data: " << res << std::endl;
    }
    Sleep(100);
  }

  // Signal the processing thread to stop and wait for it to finish
  stop_processing = true;
  buffer_cv.notify_all();
  processing_thread.join();

  // Clean up
  delete_signal_processor(rust_processor);
  FreeLibrary(hinstLib);

  // free samples
  for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
  {
    free(trial.samples[i]);
  }

  // Close the Blackrock system
  res = cbSdkClose(0);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cerr << "ERROR: cbSdkClose" << std::endl;
    return 1;
  }

  return 0;
}