#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include "cbsdk.h"
#include <iostream>
#include <string.h>
#include <thread>
#include <chrono>

using namespace std;

int main(int argc, char *argv[])
{
  cout << "Starting Blackrock continuous data collection..." << endl;

  // Open system
  cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_DEFAULT);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cout << "ERROR: cbSdkOpen failed with code: " << res << endl;
    return 1;
  }

  // Give the system time to initialize
  this_thread::sleep_for(chrono::milliseconds(500));

  // Setup the first channel only (continuous recording at 30kHz)
  cbPKT_CHANINFO chan_info;

  // IMPORTANT: Initialize the structure to zero
  memset(&chan_info, 0, sizeof(cbPKT_CHANINFO));

  // Get current channel configuration
  res = cbSdkGetChannelConfig(0, 1, &chan_info);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cout << "ERROR: cbSdkGetChannelConfig failed with code: " << res << endl;
    cbSdkClose(0);
    return 1;
  }

  // Check if channel is valid
  if (!(chan_info.chancaps & cbCHAN_EXISTS))
  {
    cout << "ERROR: Channel 1 does not exist" << endl;
    cbSdkClose(0);
    return 1;
  }

  // Check if channel supports analog input
  if (!(chan_info.chancaps & cbCHAN_AINP))
  {
    cout << "ERROR: Channel 1 does not support analog input" << endl;
    cbSdkClose(0);
    return 1;
  }

  // Change configuration
  chan_info.smpgroup = 5;  // continuous sampling rate (30kHz)
  chan_info.smpfilter = 0; // no filter

  // Set channel configuration
  res = cbSdkSetChannelConfig(0, 1, &chan_info);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cout << "ERROR: cbSdkSetChannelConfig failed with code: " << res << endl;
    cbSdkClose(0);
    return 1;
  }

  // Give hardware time to apply settings
  this_thread::sleep_for(chrono::milliseconds(100));

  // Ask to send trials (only continuous data)
  res = cbSdkSetTrialConfig(0, 1, 0, 0, 0, 0, 0, 0, false,
                            0, cbSdk_CONTINUOUS_DATA_SAMPLES, 0, 0, 0, true);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cout << "ERROR: cbSdkSetTrialConfig failed with code: " << res << endl;
    cbSdkClose(0);
    return 1;
  }

  // Create structure to hold the data
  cbSdkTrialCont trial;
  memset(&trial, 0, sizeof(cbSdkTrialCont));

  // Allocate memory for samples
  for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
  {
    trial.samples[i] = calloc(cbSdk_CONTINUOUS_DATA_SAMPLES, sizeof(INT16));
    if (trial.samples[i] == NULL)
    {
      cout << "ERROR: Memory allocation failed for channel " << i << endl;
      // Clean up already allocated memory
      for (int j = 0; j < i; j++)
      {
        free(trial.samples[j]);
      }
      cbSdkClose(0);
      return 1;
    }
  }

  // Initialize the buffer with trial info
  res = cbSdkInitTrialData(0, 1, NULL, &trial, NULL, NULL);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cout << "ERROR: cbSdkInitTrialData failed with code: " << res << endl;
    // Free memory
    for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
    {
      free(trial.samples[i]);
    }
    cbSdkClose(0);
    return 1;
  }

  // Give system time to start streaming
  this_thread::sleep_for(chrono::milliseconds(100));

  int loop_count = 0;
  int total_samples_received = 0;

  // Main loop - run for 10 seconds
  while (true)
  {
    loop_count++;

    // Get the data samples
    res = cbSdkGetTrialData(0, 1, NULL, &trial, NULL, NULL);
    if (res == CBSDKRESULT_SUCCESS)
    {
      // Check if we have data for channel 1
      if (trial.count > 0 && trial.num_samples[0] > 0)
      {
        cout << "Loop " << loop_count << ": Received "
             << trial.num_samples[0] << " samples from channel "
             << trial.chan[0] << endl;

        INT16 *samples = (INT16 *)trial.samples[0];

        // Print first few samples as verification
        int samples_to_print = min((uint32_t)10, trial.num_samples[0]);
        cout << "First " << samples_to_print << " samples: ";
        for (int z = 0; z < samples_to_print; z++)
        {
          cout << samples[z] << " ";
        }
        cout << endl;

        total_samples_received += trial.num_samples[0];
      }
      else
      {
        cout << "Loop " << loop_count << ": No new data available" << endl;
      }
    }
    else
    {
      cout << "ERROR: cbSdkGetTrialData failed with code: " << res << endl;
    }

    // Sleep for 100ms
    Sleep(100);
  }

  cout << "Total samples received: " << total_samples_received << endl;
  cout << "Expected approximate total: " << (30000 * 10) << " (30kHz * 10 seconds)" << endl;

  // Free trial memory
  for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
  {
    if (trial.samples[i] != NULL)
    {
      free(trial.samples[i]);
    }
  }

  // Close system (only once!)
  res = cbSdkClose(0);
  if (res != CBSDKRESULT_SUCCESS)
  {
    cout << "ERROR: cbSdkClose failed with code: " << res << endl;
    return 1;
  }

  cout << "Program completed successfully" << endl;
  return 0;
}