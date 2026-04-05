Original sample rate (as in the *.mat files) was 512Hz

So dividing sample numbers in the *.mrk files by 512 will give you the slow wave times in seconds

Data in the *.npy files has been upsampled by linear interpolation to 30kHz, to match the rate of acquisition on the Blackrock machine

The NPMK GitHub repository has MATLAB (and possibly Python?) functions to convert these data into *.nsx format