# Minimum required version of CMake
cmake_minimum_required(VERSION 3.15)

# Set the project name
project(DNB VERSION 0.10.0)

# Use C++14 standard
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# Specify where to find the CBSDK include files
include_directories("C:/CereLink/CBSDK-7.6.1-win64/include")

# Specify where to find the CBSDK libraries
link_directories("C:/CereLink/CBSDK-7.6.1-win64/lib")

# Add the main.cpp file in the src folder as a source file
add_executable(DNB src/main.cpp)

# Link the CBSDK library (this assumes the CBSDK library is named libcbsdk.a for MinGW)
target_link_libraries(DNB PRIVATE cbsdk)  # Adjust if necessary

# Bugfix from CereLink wiki
target_compile_definitions(DNB PRIVATE NO_AFX)
