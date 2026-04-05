# Minimum required version of CMake
cmake_minimum_required(VERSION 3.15)

# Set the project name
project(DNB VERSION 1.4.0)

# Use C++14 standard
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED True)

# Allow CBSDK path to be set from command line
if(NOT DEFINED CBSDK_PATH)
    if(WIN32)
        set(CBSDK_PATH "C:/CereLink/CBSDK-7.6.1-win64")
    else()
        set(CBSDK_PATH "/opt/cbsdk")
    endif()
endif()

# Specify where to find the CBSDK include files
include_directories("${CBSDK_PATH}/include")

# If we're copying headers locally, also include src directory
include_directories("${CMAKE_SOURCE_DIR}/src")

# Specify where to find the CBSDK libraries
if(WIN32)
    link_directories("${CBSDK_PATH}/lib")
else()
    link_directories("${CBSDK_PATH}/lib64")
    link_directories("${CBSDK_PATH}/bin")
endif()

# Add the main executable
add_executable(DNB src/main.cpp)

# Platform-specific settings
if(WIN32 OR MINGW)
    # Windows-specific settings
    target_compile_definitions(DNB PRIVATE NO_AFX WIN32_LEAN_AND_MEAN NOMINMAX)
    
    if(MINGW)
        # Force static linking for MinGW
        set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -static-libgcc -static-libstdc++")
        set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -Wl,--enable-stdcall-fixup")
        
        # Link libraries
        target_link_libraries(DNB PRIVATE 
            cbsdk
            winmm
            ws2_32
            user32
            gdi32
            setupapi
            ole32
            oleaut32
            iphlpapi
        )
    elseif(MSVC)
        # MSVC-specific flags
        set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} /EHsc /MP")
        set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
        
        target_link_libraries(DNB PRIVATE 
            cbsdk.lib
            winmm.lib
        )
    endif()
endif()