# Minimum required version of CMake
cmake_minimum_required(VERSION 3.15)

# Set the project name
project(DNB VERSION 1.2.1)

# Add this near the top after project()
if(MINGW)
    # Force static linking of runtime libraries for MinGW
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -static-libgcc -static-libstdc++")
    
    # Add Windows system libraries that CBSDK might depend on
    target_link_libraries(DNB PRIVATE ws2_32 user32 gdi32)
endif()

# Use C++14 standard
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# Specify where to find the CBSDK include files
include_directories("C:/CereLink/CBSDK-7.6.1-win64/include")

# Specify where to find the CBSDK libraries
link_directories("C:/CereLink/CBSDK-7.6.1-win64/lib")

# Add the main.cpp file in the src folder as a source file
add_executable(DNB src/main.cpp)

# Link against the correct library name based on compiler
if(MSVC)
    target_link_libraries(DNB PRIVATE cbsdk.lib)
else()
    target_link_libraries(DNB PRIVATE cbsdk)
endif()

# Link the winmm library for playing audio (use correct name for MSVC)
if(MSVC)
    target_link_libraries(DNB PRIVATE winmm.lib)
else()
    target_link_libraries(DNB PRIVATE winmm)
endif()

# Bugfix from CereLink wiki
target_compile_definitions(DNB PRIVATE NO_AFX)

# Add MSVC-specific flags
if(MSVC)
    # Disable specific warnings and set runtime library
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /EHsc /MP")
    # Use Multi-threaded DLL runtime library
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
endif()