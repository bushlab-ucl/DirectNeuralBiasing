
#include <windows.h>
#include "cbsdk.h"
#include <iostream>
#include <string.h>
using namespace std;

/*
Author: Joshua Robinson
Company: Blackrock Microsystems
Contact: support@blackrockmicro.com

Function Description: Checks system (Neuroprocessor) for time and comments in command window . 
*/

	int main(int argc, char *argv[])
	{
		UINT32 nInstance = 0;
		UINT32 cbtime = 0;

		//open system
		cbSdkResult res = cbSdkOpen(0, CBSDKCONNECTION_DEFAULT);
		if (res != CBSDKRESULT_SUCCESS)
		{
			cout << "ERROR: cbSdkOpen" << endl;
			return 1;
		}


		for (int x = 0; x < 100000; x++) {

			res = cbSdkGetTime(nInstance, &cbtime);
			if (res != CBSDKRESULT_SUCCESS) {
				cout << "get time error" << endl;

				}

			cout << cbtime << endl;



		}


};
