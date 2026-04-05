#include <iostream>
#define WIN32_LEAN_AND_MEAN // Exclude rarely-used stuff from Windows headers
#include <windows.h>
#include "cbsdk.h" // Make sure this matches the actual header name in the CBSDK

int main()
{
  std::cout << "Initializing CereLink SDK..." << std::endl;

  // Initialize CBSDK (using 0 for NSP instance 0)
  cbSdkResult result = cbSdkOpen(0);
  if (result == CBSDKRESULT_SUCCESS)
  {
    std::cout << "CereLink SDK Initialized successfully!" << std::endl;
  }
  else
  {
    std::cerr << "Failed to initialize CereLink SDK." << std::endl;
  }

  // Clean up by closing the SDK
  cbSdkClose(0);

  return 0;
}
