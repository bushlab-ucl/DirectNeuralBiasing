#include <windows.h>
#include "cbsdk.h"
#include <iostream>
#include <string.h>
using namespace std;
/*
Author: Joshua Robinson
Company: Blackrock Microsystems
Contact: support@blackrockmicro.com

Function Description: Loops for a defined period of time and retrieves comments from the Neural Signal Processor firmware. 
*/

int main(int argc, char *argv[])
{

	//open system
	cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_UDP);
	if (res != CBSDKRESULT_SUCCESS)
	{
		cout << "ERROR: cbSdkOpen" << endl;
		return 1;
	}

	// Number of comments to buffer
	UINT32 CommentsCount = 100;

	//ask to send trials (only comment and event data)
	res = cbSdkSetTrialConfig(0, 1, 0, 0, 0, 0, 0, 0, false, 0, 0, cbSdk_EVENT_DATA_SAMPLES, CommentsCount, 0, false);
	if (res != CBSDKRESULT_SUCCESS)
	{
		cout << "ERROR: cbSdkSetTrialConfig" << endl;
		return 1;
	}


	//main loop do for a defined time
	int loop_count = 0;
	while (loop_count < 100)
	{
		loop_count = loop_count + 1;

		//create structure to hold the data
		cbSdkTrialComment trialcomment;

		// For event based data, init must be called in the loop.
		cbSdkResult res2 = cbSdkInitTrialData(0, 1, NULL, NULL, &trialcomment, NULL);
		if (res2 != CBSDKRESULT_SUCCESS)
		{
			cout << "ERROR: cbSdkInitTrialData" << endl;
		}

		cout << "Number of Available Comments" << endl;
		cout << trialcomment.num_samples << endl;

		// reserve memory
		if (trialcomment.num_samples) {
			trialcomment.comments = (UINT8 * *)malloc(trialcomment.num_samples * sizeof(UINT8 *));
			trialcomment.charsets = (UINT8 *)malloc(trialcomment.num_samples * sizeof(UINT8 *));
			trialcomment.rgbas = (UINT32 *)malloc(trialcomment.num_samples * sizeof(UINT32 *));
			trialcomment.timestamps = malloc(trialcomment.num_samples * sizeof(UINT32));
			
			for (int i = 0; i < trialcomment.num_samples; i++) {
				trialcomment.comments[i] = (UINT8 *)malloc(256 * sizeof(UINT8));
			}
		}

		// after data is initialized and memory setup, get actual data
		cbSdkResult res3 = cbSdkGetTrialData(0, 1, NULL, NULL, &trialcomment, NULL);
		if (res3 == CBSDKRESULT_SUCCESS)
		{
			//if comments exist
			if (trialcomment.num_samples > 0) {
				for (int i = 0; i < trialcomment.num_samples; i++) {
					cout << (char*)trialcomment.comments[i] << endl;
				}
			}
		}
		else
		{
			cout << "ERROR: cbSdkGetTrialData" << endl;
		}

		//sleep for some ms
		Sleep(100);
	}


	//close system
	res = cbSdkClose(0);
	if (res != CBSDKRESULT_SUCCESS)
	{
		cout << "ERROR: cbSdkClose" << endl;
		return 1;
	}
	cbSdkResult close = cbSdkClose(0);
	return 0;
}

