// #include "stdafx.h"
#include <windows.h>
#include "cbsdk.h"
#include "Test/TestRoutines.h"
#include <iostream>
#include <string.h>
#include <chrono>
using namespace std;

/*
Blackrock Author: Joshua Robinson
Company: Blackrock Microsystems
Contact: support@blackrockmicro.com

UCL Author: Dan Humphries
Lab: Human Electrophysiology Lab, UCL NPP
Contact: d.humphries@ucl.ac.uk

Blackrock Function Description: Gets values from continuous trial data and prints them to the command prompt
UCL Research Function Description: On each cycle, runs a rust function to perform real-time analysis of the data.
*/

const double fs = 30000.0;						 // Sampling rate
const double f0_swr = 100.0;					 // SWR frequency
const double f0_interictal = 220.0;		 // Interictal Spike frequency
const double threshold_swr = 1;				 // SWR threshold
const double threshold_interictal = 1; // Interictal Spike threshold

#define RUN_TEST_ROUTINES true

// Define function pointers for the filter
typedef void *(__cdecl *CreateFilterStateFunc)(double, double, double);
typedef void(__cdecl *DeleteFilterStateFunc)(void *);
typedef bool(__cdecl *ProcessSingleSampleFunc)(void *, double);
typedef bool(__cdecl *ProcessSampleChunkFunc)(void *, double *, size_t);

// Define function pointers for the test routines
// typedef void(__cdecl* ProcessDataFunc)(const INT16*, size_t);
// typedef void(__cdecl* ProcessDataComplexFunc)(INT16*, size_t);

int main(int argc, char *argv[])
{

	// Load the Rust library
	HINSTANCE hinstLib = LoadLibrary(TEXT("..\\..\\rustlib\\target\\release\\dnb.dll"));
	if (hinstLib == NULL)
	{
		std::cerr << "DLL failed to load!" << std::endl;
		return 1;
	}

	// Load the test routines
	TestRoutines testRoutines;
	if (!testRoutines.loadRustLibrary())
	{
		std::cerr << "Failed to load Rust library" << std::endl;
		return 1;
	}

	// Load filter functions
	CreateFilterStateFunc create_filter_state = (CreateFilterStateFunc)GetProcAddress(hinstLib, "create_filter_state");
	DeleteFilterStateFunc delete_filter_state = (DeleteFilterStateFunc)GetProcAddress(hinstLib, "delete_filter_state");
	ProcessSingleSampleFunc process_single_sample = (ProcessSingleSampleFunc)GetProcAddress(hinstLib, "process_single_sample");
	ProcessSampleChunkFunc process_sample_chunk = (ProcessSampleChunkFunc)GetProcAddress(hinstLib, "process_sample_chunk");

	if (create_filter_state == NULL || delete_filter_state == NULL || process_single_sample == NULL || process_sample_chunk == NULL)
	{
		std::cerr << "Filter functions not found!" << std::endl;
		FreeLibrary(hinstLib);
		return 1;
	}

	//// Load Rust Test functions
	// ProcessDataFunc process_data = (ProcessDataFunc)GetProcAddress(hinstLib, "process_data");
	// ProcessDataComplexFunc process_data_complex = (ProcessDataComplexFunc)GetProcAddress(hinstLib, "process_data_complex");

	// if (process_data == NULL || process_data_complex == NULL)
	//{
	//	std::cerr << "Rust Test functions not found!" << std::endl;
	//	FreeLibrary(hinstLib);
	//	return 1;
	// }

	// open system
	cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_DEFAULT);
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
	chan_info.smpgroup = 5; // continuous sampling rate (30kHz)
	// set channel configuration
	r = cbSdkSetChannelConfig(0, 1, &chan_info); // note: channels start at 1

	// ask to send trials (only continuous data)
	res = cbSdkSetTrialConfig(0, 1, 0, 0, 0, 0, 0, 0, false, 0, cbSdk_CONTINUOUS_DATA_SAMPLES, 0, 0, 0, true);
	if (res != CBSDKRESULT_SUCCESS)
	{
		cout << "ERROR: cbSdkSetTrialConfig" << endl;
		return 1;
	}

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

	// Prepare loop
	int loop_count, loop_end;
	loop_count = 0;
	loop_end = 10;

	auto start = std::chrono::high_resolution_clock::now();
	auto end = start;

	// Create filter
	void *filter_swr = create_filter_state(f0_swr, fs, threshold_swr);
	void *filter_interictal = create_filter_state(f0_interictal, fs, threshold_interictal);

	if (filter_swr == NULL || filter_interictal == NULL)
	{
		std::cerr << "Failed to create filters!" << std::endl;
		FreeLibrary(hinstLib);
		return 1;
	}
	// main loop do for 10 seconds
	while (loop_count < loop_end)
	{
		loop_count = loop_count + 1;

		// get the data samples
		res = cbSdkGetTrialData(0, 1, NULL, &trial, NULL, NULL);
		if (res == CBSDKRESULT_SUCCESS)
		{
			// if the trial is not empty
			start = std::chrono::high_resolution_clock::now();
			if (trial.count > 0)
			{
				cout << "Channel 1" << endl;
				cout << "Number of samples: " << trial.num_samples[0] << endl;
				INT16 *myIntPtr = (INT16 *)trial.samples[0]; // Look at only Channel 1 (index 0)
				double *doubleArray = new double[trial.num_samples[0]];

				for (size_t i = 0; i < trial.num_samples[0]; i++)
				{
					// cout << myIntPtr[i] << endl; // Print each sample#
					doubleArray[i] = static_cast<double>(myIntPtr[i]);
				}

				// if (RUN_TEST_ROUTINES)
				//{
				//	TestRoutines::RunTestRoutines(testRoutines, myIntPtr, trial.num_samples[0]);
				// }

				// Process data with filters
				bool swr_detected = process_sample_chunk(filter_swr, doubleArray, trial.num_samples[0]);
				bool interictal_detected = process_sample_chunk(filter_interictal, doubleArray, trial.num_samples[0]);

				if (interictal_detected)
				{
					swr_detected = false; // Reset SWR detection if Interictal spike is detected
				}

				if (swr_detected)
				{
					std::cout << "SWR Detected" << std::endl;
				}
			}
		}
		else
		{
			cout << "ERROR: cbSdkGetTrialData" << endl;
		}

		end = std::chrono::high_resolution_clock::now();

		std::cout << "Time elapsed in Rust Filter function: "
							<< std::chrono::duration_cast<std::chrono::microseconds>(end - start).count()
							<< " microseconds" << std::endl;

		// sleep for some ms
		Sleep(10);
	}

	// free trial
	for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
	{
		free(trial.samples[i]);
	}

	// free library + filters
	delete_filter_state(filter_swr);
	delete_filter_state(filter_interictal);
	FreeLibrary(hinstLib);

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
