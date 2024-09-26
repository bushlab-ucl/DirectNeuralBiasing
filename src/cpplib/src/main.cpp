// #include "stdafx.h"
#define WIN32_LEAN_AND_MEAN // Exclude rarely-used stuff from Windows headers
// #include "stdafx.h"
#include <windows.h>
#include "cbsdk.h"
#include <iostream>
#include <string.h>
using namespace std;

/*
Author: Joshua Robinson
Company: Blackrock Microsystems
Contact: support@blackrockmicro.com

Function Description: Gets values from continuous trial data and prints them to the command prompt
*/

int main(int argc, char *argv[])
{

	// open system
	// cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_DEFAULT);
	cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_UDP);
	if (res != CBSDKRESULT_SUCCESS)
	{
		cout << "ERROR: cbSdkOpen" << endl;
		return 1;
	}

	// setup the first channel only (continuous recording at 30kHz, no filter)
	cbPKT_CHANINFO chan_info;
	// get current channel configuration
	cbSdkResult r = cbSdkGetChannelConfig(0, 1, &chan_info);
	// change configuration
	chan_info.smpgroup = 5;											 // continuous sampling rate (30kHz)
																							 // set channel configuration
	r = cbSdkSetChannelConfig(0, 1, &chan_info); // note: channels start at 1

	// ask to send trials (only continuous data)
	res = cbSdkSetTrialConfig(0, 1, 0, 0, 0, 0, 0, 0, false, 0, cbSdk_CONTINUOUS_DATA_SAMPLES, 0, 0, 0, true);
	if (res != CBSDKRESULT_SUCCESS)
	{
		cout << "ERROR: cbSdkSetTrialConfig" << endl;
		return 1;
	}

	Sleep(1000);

	// create structure to hold the data
	cbSdkTrialCont trial;
	// alloc memory for samples
	for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
	{
		trial.samples[i] = malloc(cbSdk_CONTINUOUS_DATA_SAMPLES * sizeof(INT16));
	}

	// initialize the buffer with trial infos
	cbSdkResult res1 = cbSdkInitTrialData(0, 1, NULL, &trial, NULL, NULL);
	if (res1 != CBSDKRESULT_SUCCESS)
	{
		cout << "ERROR: cbSdkInitTrialData" << endl;
	}

	int loop_count;
	loop_count = 0;

	// main loop do for 10 seconds
	while (loop_count < 1000)
	{
		loop_count = loop_count + 1;

		// get the data samples
		res = cbSdkGetTrialData(0, 1, NULL, &trial, NULL, NULL);
		if (res == CBSDKRESULT_SUCCESS)
		{
			// if the trial is not empty
			if (trial.count > 0)
			{
				cout << "Channel 1" << endl;
				cout << "Channel 1" << endl;
				INT16 *myIntPtr = (INT16 *)trial.samples[0]; // Look at only Channel 1 (index 0)

				for (int z = 0; z < trial.num_samples[0]; z++)
				{
					cout << myIntPtr[z] << endl; // Print each sample
				}
			}
			else
			{
				cout << "No trial data" << endl;
			}
		}
		else
		{
			cout << "ERROR: cbSdkGetTrialData" << endl;
		}

		// sleep for some ms
		Sleep(100);
	}

	// free trial
	for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
	{
		free(trial.samples[i]);
	}

	// close system
	res = cbSdkClose(0);
	if (res != CBSDKRESULT_SUCCESS)
	{
		cout << "ERROR: cbSdkClose" << endl;
		return 1;
	}
	cbSdkResult close = cbSdkClose(0);
	return 0;
}
