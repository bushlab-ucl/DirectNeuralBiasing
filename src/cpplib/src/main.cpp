#define WIN32_LEAN_AND_MEAN // Exclude rarely-used stuff from Windows headers
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

// Rust FFI declarations
typedef void *(__cdecl *CreateSignalProcessorFunc)(bool verbose, double fs, size_t channel);
typedef void(__cdecl *DeleteSignalProcessorFunc)(void *processor);
typedef void *(__cdecl *RunChunkFunc)(void *processor, const double *data, size_t length);

using namespace std;

// Constants
const double fs = 30000.0;       // Sampling rate (30kHz)
const size_t buffer_size = 1024; // Buffer size for real-time processing (adjust as needed)
const size_t num_buffers = 2;    // Number of reusable buffers (double buffering)

// Thread-safe queue for processing buffers
std::queue<double *> buffer_queue;
std::mutex queue_mutex;
std::condition_variable buffer_cv;
bool stop_processing = false; // Flag to stop the processing thread

// Function to load Rust functions from DLL
bool load_rust_functions(HINSTANCE &hinstLib, CreateSignalProcessorFunc &create_signal_processor,
                         DeleteSignalProcessorFunc &delete_signal_processor, RunChunkFunc &run_chunk)
{
  hinstLib = LoadLibrary(TEXT("./direct_neural_biasing.dll"));
  Sleep(1000);
  if (hinstLib == NULL)
  {
    std::cerr << "Failed to load Rust DLL!" << std::endl;
    return false;
  }

  create_signal_processor = (CreateSignalProcessorFunc)GetProcAddress(hinstLib, "create_signal_processor");
  delete_signal_processor = (DeleteSignalProcessorFunc)GetProcAddress(hinstLib, "delete_signal_processor");
  run_chunk = (RunChunkFunc)GetProcAddress(hinstLib, "run_chunk");

  if (create_signal_processor == NULL || delete_signal_processor == NULL || run_chunk == NULL)
  {
    std::cerr << "Failed to load Rust functions!" << std::endl;
    FreeLibrary(hinstLib);
    return false;
  }

  return true;
}

// Function to play an audio pulse
void play_audio_pulse()
{
  // Specify the path to a .wav file (make sure the file exists in the specified location)
  const char *sound_file = "./airhorn.wav"; // Replace with your .wav file path

  // Play the sound asynchronously (so it doesn't block the main thread)
  PlaySoundA(sound_file, NULL, SND_FILENAME | SND_ASYNC);
}

// Processing thread function
void process_buffer_loop(void *rust_processor, RunChunkFunc run_chunk)
{
  while (true)
  {
    std::unique_lock<std::mutex> lock(queue_mutex);
    buffer_cv.wait(lock, []
                   { return !buffer_queue.empty() || stop_processing; });

    if (stop_processing && buffer_queue.empty())
      break;

    double *buffer = buffer_queue.front();
    buffer_queue.pop();
    lock.unlock();

    // Time the processing start
    auto start_time = std::chrono::high_resolution_clock::now();

    // Process the buffer in Rust
    void *result = run_chunk(rust_processor, buffer, buffer_size);

    // Time the processing end
    auto end_time = std::chrono::high_resolution_clock::now();
    auto processing_time = std::chrono::duration_cast<std::chrono::milliseconds>(end_time - start_time).count();

    // Print the first object from the result
    if (result != nullptr)
    {
      // Rust returned a valid timestamp
      double timestamp = *reinterpret_cast<double *>(result);
      play_audio_pulse(); // Play an audio pulse
      std::cout << "Triggered at timestamp: " << timestamp << " seconds since UNIX epoch." << std::endl;
      std::cout << "Processing time: " << processing_time << " ms" << std::endl;

      // After processing the result, free the memory allocated in Rust
      delete static_cast<double *>(result);
    }
    else
    {
      // No trigger, Rust returned nullptr
      // std::cout << "No trigger event detected." << std::endl;
    }

    // Print the processing time
    // std::cout << "Processing time: " << processing_time << " ms" << std::endl;

    // The buffer will be reused, so no need to delete[] buffer.
  }
}

int main(int argc, char *argv[])
{
  HINSTANCE hinstLib;
  CreateSignalProcessorFunc create_signal_processor;
  DeleteSignalProcessorFunc delete_signal_processor;
  RunChunkFunc run_chunk;

  // Load the Rust library and functions
  if (!load_rust_functions(hinstLib, create_signal_processor, delete_signal_processor, run_chunk))
  {
    return 1;
  }

  // Initialize Rust Signal Processor (for channel 1)
  void *rust_processor = create_signal_processor(true, fs, 1);
  if (rust_processor == NULL)
  {
    std::cerr << "Failed to create Rust signal processor!" << std::endl;
    FreeLibrary(hinstLib);
    return 1;
  }

  // Start the processing thread
  std::thread processing_thread(process_buffer_loop, rust_processor, run_chunk);

  // Open Blackrock system
  cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_DEFAULT);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cerr << "ERROR: cbSdkOpen" << std::endl;
    return 1;
  }

  // Configure the first channel (continuous recording at 30kHz)
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

  // Preallocate a fixed set of buffers for double buffering
  double *buffers[num_buffers];
  for (size_t i = 0; i < num_buffers; i++)
  {
    buffers[i] = new double[buffer_size]; // Preallocated reusable buffers
  }
  size_t buffer_index = 0; // Track the current buffer index

  // Allocate memory for the trial data
  cbSdkTrialCont trial;
  trial.samples[0] = malloc(buffer_size * sizeof(INT16)); // Only using one channel for now

  // Initialize the trial data structure
  res = cbSdkInitTrialData(0, 1, NULL, &trial, NULL, NULL);
  if (res != CBSDKRESULT_SUCCESS)
  {
    std::cerr << "ERROR: cbSdkInitTrialData" << std::endl;
    return 1;
  }

  int loop_count = 0;
  const int max_loops = 1000; // Number of loops to run

  // Main loop to collect data
  while (true)
  {
    loop_count++;

    // Get the data samples from Blackrock
    res = cbSdkGetTrialData(0, 1, NULL, &trial, NULL, NULL);
    if (res == CBSDKRESULT_SUCCESS && trial.count > 0)
    {
      INT16 *int_samples = (INT16 *)trial.samples[0]; // Get samples for channel 1

      // Copy samples into the preallocated buffer
      double *active_buffer = buffers[buffer_index];
      for (size_t i = 0; i < trial.num_samples[0]; i++)
      {
        active_buffer[i] = static_cast<double>(int_samples[i]);
      }

      // Push the filled buffer into the processing queue
      {
        std::lock_guard<std::mutex> lock(queue_mutex);
        buffer_queue.push(active_buffer);
      }
      buffer_cv.notify_one(); // Notify the processing thread

      // Cycle through the buffers (double-buffering logic)
      buffer_index = (buffer_index + 1) % num_buffers;
    }
    else
    {
      std::cerr << "No trial data or ERROR in cbSdkGetTrialData" << std::endl;
    }
  }

  // Clean up
  free(trial.samples[0]);

  // Signal the processing thread to stop and wait for it to finish
  {
    std::lock_guard<std::mutex> lock(queue_mutex);
    stop_processing = true;
  }
  buffer_cv.notify_one();
  processing_thread.join();

  delete_signal_processor(rust_processor);
  FreeLibrary(hinstLib);

  // Free the preallocated buffers
  for (size_t i = 0; i < num_buffers; i++)
  {
    delete[] buffers[i];
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