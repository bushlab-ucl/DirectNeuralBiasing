//////////////////////////////////////////////////////////////////////////////
/// @file Channel_Unit_TTL.c
/// @Contributor:  Greg Palis
/// @copyright (c) Copyright Blackrock Microsystems
/// @brief
///    Sample Extension code that triggers 4-bit TTL for channel of sorted spike and 3 bit TTL for unit of spike
/// @date updated 4/13/2020
///

/// include standard headers

#include <string.h> ///< the string header includes standard functions for working with strings and arrays
#include <stdio.h>  ///< the Standard Input Output header include functions for input/output functionality
#include <stdlib.h> ///< the Standard Library header includes many basic functions for variable manipulation and storage

/// include the extension-specific headers

#include "../ExtensionCommon/nspPlugin.h"
#include "../ExtensionCommon/nspChanTrigPlugin.h"

/// define the boolean structure for C

#ifndef BOOL
#define BOOL int
#endif

#ifndef TRUE
#define TRUE 1 
#endif

#ifndef FALSE
#define FALSE 0 
#endif

/// Define number of data points to retrieve from buffers

#define REQSPIKES 16  ///< set the number of spikes to pull from the spike buffer

/// Create data structures to hold spikes

cbExtChanTrigSpikes spikes;
cbExtSpikeElement spikeElement[REQSPIKES];

// Define channel numbers to use for specific extensions functions

uint16_t g_nCheckingLoadStatus = 0;     // Disable getting data
uint16_t g_nAllFull = 0;          // set to non-zero if all buffers are full (to prevent sending lots of messages)
int msg = 0;
uint16_t a = 8;
// TtlOut takes in the channel and unit of sorted spikes 
// Triggers 4 bit output for channel number and 3 bit output for unit number
// Channel number is compared, in binary form, with 8 (1000), 4 (0100), 2 (0010) and 1 (0001)
void TtlOut(nChan, nUnit)
{
	char logMsg[128];
	memset(logMsg, 0, sizeof(logMsg));
	if (msg < 10)
	{
		sprintf(logMsg, "TTLOUT Called\n");
		cbExtLogEvent(logMsg);
		msg++;
	}
	// Do a bitwise comparison of the channel number of the detected spike with 1000, 0100, 0010, and 0001
	//  
	// Analog output command accepts to inputs, analog output channel number and waverorm number
	// Waveform number refers to the analog waveform created in Central
	// The channel used (1 in this case) must be set to function "extension" within Central GUI

	if (nChan & (1 << 3))
	{
		cbExtChanTrigAnalogOutput(0, 0);
	}
	if (nChan & (1 << 2))
	{
		cbExtChanTrigAnalogOutput(1, 0);
	}
	if (nChan & (1 << 1))
	{
		cbExtChanTrigAnalogOutput(2, 0);
	}
	if (nChan & (1 << 0))
	{
		cbExtChanTrigAnalogOutput(3, 0);
	}

	// Do a bitwise comparison of the unit number of the detected spike with 100, 010, and 001
	//  
	// Digital output command accepts to inputs, digital output channel number and waverorm number
	// Waveform number refers to the digital waveform created in Central
	// The channel used (1 in this case) must be set to function "extension" within Central GUI
	if (nUnit & (1 << 2))
	{
		cbExtChanTrigDigitalOutput(0, 0);
	}
	if (nUnit & (1 << 1))
	{
		cbExtChanTrigDigitalOutput(1, 0);
	}
	if (nUnit & (1 << 0))
	{
		cbExtChanTrigDigitalOutput(2, 0);
	}

}


/// Any time a spike is detected on the NSP this function is called in the main loop below
/// @brief  A spike has been found so feed the channel and unit number into ttl output function
void ProcessSpike(void)
{
	int nIndex;            // initialize an index interger

	// First check to see if multiple spikes were detected on the same sample
	if (spikes.isCount.nCountSpikes > 1)
		// If multiple spikes detected set a flag bit
	{
		cbExtChanTrigDigitalOutput(3, 0);
	}

	/// index through from 0 through to the number of spikes detected
	// Currently this will only send the TTL's for one of the spikes in the buffer
	// Handling multiple could involve the flag bit above or other methods
	for (nIndex = 0; nIndex < spikes.isCount.nCountSpikes; ++nIndex)
	{
		// if there is a spike on the first 16 channels clasified as a unit
		if ((spikes.isSpike[nIndex].nChan < 16) && (spikes.isSpike[nIndex].nUnit > 0))
		{
			// Print the time, channel number and unit number detected
				// This is where we call the output function and the magic happens
			TtlOut(spikes.isSpike[nIndex].nChan, spikes.isSpike[nIndex].nUnit);
		}
	}
}

// cbExtMainLoop runs continualy while extension is running on the NSP
// code before "while (res != CBEXTRESULT_EXIT)" runs once
// code within "while (res != CBEXTRESULT_EXIT)" runs for the life of the extension
//
cbExtResult cbExtMainLoop(cbExtSettings* settings)
{
	cbExtResult res = CBEXTRESULT_SUCCESS;    // set the result to success before starting

	// initialize the message buffer
	char logMsg[128];
	memset(logMsg, 0, sizeof(logMsg));

	// prepare spike input structure
	spikes.isSpike = &spikeElement[0];
	spikes.isCount.nCountSpikes = REQSPIKES;

	// This is the main loop of the extension
	// Ideally this loop is fast enough to run multiple times per 33 microsecond sample
	while (res != CBEXTRESULT_EXIT)
	{
		/// Check if spike detected during this sample
		memset(spikeElement, 0, sizeof(spikeElement));      // zero out the spike memory structure
		spikes.isCount.nCountSpikes = REQSPIKES;            // set the number of spikes to check for to REQSPIKES

		res = cbExtChanTrigGetSpikes(&spikes);              // save spikes to the spikes structure

		if (res == CBEXTRESULT_EXIT)                        // error so we'll exit
		{
			sprintf(logMsg, "Error getting spikes\n");
			cbExtLogEvent(logMsg);
			break;

		}
		else if (res == CBEXTRESULT_SUCCESS)                // process the spike if there is one
		{
			ProcessSpike();
		}
		else
		{
			//printf("some spike error occured %d\n", res);   // if an error occurs, print it
		}
	}
}

/// cbExtSetup has to be included in all extensions and holds the basic information about the extension
cbExtResult cbExtSetup(cbExtInfo* info)
{
	// The pieces in info that are not set here will have 0 as default, which disables them
	info->nPluginVer = 1;                                            // Give this a version
	info->nWarnCommentsThreshold = 90;                               // Warn on 90% buffer
	strncpy(info->szName, "Channel Unit TTL", sizeof(info->szName)); // set the extension name
	cbExtCommentMask iMask;       // mask allowing certain types of comments to enter buffer
	iMask.nCharsetMask = 0x90;    // Interested in charsets of 128 and 16 (0x80 + 0x10)
	iMask.flags = CBEXT_CMT_NONE; // also want normal comments, but am not interested in NeuroMotive events
	info->iMask = iMask;

	return CBEXTRESULT_SUCCESS;
}


/// cbExtChanTrigSetup configures signal aquisition parameters
// The pieces in info that are not set here will have 0 as default, which disables them
// Currently, all functions should be enabled

cbExtResult cbExtChanTrigSetup(cbExtChanTrigInfo* info)
{
	/// set sampling rate dividers, 30k/div = rate
	info->nDividerDigitalInput = 1; // Set sample rate divider for digital input
	info->nDividerFrontend = 1;     // Set sample rate divider for front end inputs 
	info->nDividerAnalogInput = 1;  // Set sample rate divider for analog inputs
	info->nSpikes = 1;              // capture spikes 1 = yes

	return CBEXTRESULT_SUCCESS;
}