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

#define RUN_TEST_ROUTINES true

// Define function pointers for the filter
typedef void *(__cdecl *CreateFilterFunc)(double, double, double);
typedef void(__cdecl *DeleteFilterFunc)(void *);
typedef void(__cdecl *ProcessFilterDataFunc)(void *, double *, size_t);

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

	// Get the process_data function
	typedef void(__cdecl * ProcessDataFunc)(const INT16 *, size_t);
	ProcessDataFunc process_data_rust = (ProcessDataFunc)GetProcAddress(hinstLib, "process_data");
	if (process_data_rust == NULL)
	{
		std::cerr << "Function not found!" << std::endl;
		FreeLibrary(hinstLib);
		return 1;
	}

	// Load the complex Rust function
	typedef void(__cdecl * ProcessDataComplexFunc)(INT16 *, size_t);
	ProcessDataComplexFunc process_data_complex_rust = (ProcessDataComplexFunc)GetProcAddress(hinstLib, "process_data_complex");
	if (process_data_complex_rust == NULL)
	{
		std::cerr << "Complex Rust function not found!" << std::endl;
		FreeLibrary(hinstLib);
		return 1;
	}

	// Load filter functions
	CreateFilterFunc create_filter = (CreateFilterFunc)GetProcAddress(hinstLib, "create_filter");
	DeleteFilterFunc delete_filter = (DeleteFilterFunc)GetProcAddress(hinstLib, "delete_filter");
	ProcessFilterDataFunc process_filter_data = (ProcessFilterDataFunc)GetProcAddress(hinstLib, "process_filter_data");

	if (create_filter == NULL || delete_filter == NULL || process_filter_data == NULL)
	{
		std::cerr << "Filter functions not found!" << std::endl;
		FreeLibrary(hinstLib);
		return 1;
	}

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
	 double f0 = 50.0; // Example values
	 double fs = 30000.0;
	 double q = 35.0;
	 void *filter = create_filter(f0, fs, q);
	 if (filter == NULL)
	 {
	 	std::cerr << "Failed to create filter!" << std::endl;
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
			if (trial.count > 0)
			{
				cout << "Channel 1" << endl;
				cout << "Number of samples: " << trial.num_samples[0] << endl;
				INT16 *myIntPtr = (INT16 *)trial.samples[0]; // Look at only Channel 1 (index 0)

				//if (RUN_TEST_ROUTINES)
				//{
				//	TestRoutines::RunTestRoutines(testRoutines, myIntPtr, trial.num_samples[0]);
				//}

				 start = std::chrono::high_resolution_clock::now();
				 // Process data with filter
				 double *data = new double[trial.num_samples[0]];
				 for (size_t i = 0; i < trial.num_samples[0]; ++i)
				 {
				 	data[i] = static_cast<double>(myIntPtr[i]);
				 }
				 process_filter_data(filter, data, trial.num_samples[0]);
				 for (size_t i = 0; i < trial.num_samples[0]; ++i)
				 {
				 	myIntPtr[i] = static_cast<INT16>(data[i]);
				 }
				 delete[] data;
				 end = std::chrono::high_resolution_clock::now();
				 std::cout << "Time elapsed in Rust Filter function: "
				 					<< std::chrono::duration_cast<std::chrono::microseconds>(end - start).count()
				 					<< " microseconds" << std::endl;

				for (int z = 0; z < trial.num_samples[0]; z++)
				{

					cout << myIntPtr[z] << endl; // Print each sample
				}
			}
		}
		else
		{
			cout << "ERROR: cbSdkGetTrialData" << endl;
		}

		// sleep for some ms
		Sleep(10);
	}

	// free trial
	for (int i = 0; i < cbNUM_ANALOG_CHANS; i++)
	{
		free(trial.samples[i]);
	}

	// free library
	// FreeLibrary(hinstLib);

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
