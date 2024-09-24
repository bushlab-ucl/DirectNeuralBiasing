# DNB Project - Installation and Setup Guide

## Overview
This document provides the necessary steps to build, package, and run the **DNB** application using **MinGW**. It covers setting up the environment, compiling the project, and deploying it on another machine.

## 1. Prerequisites

Before building and running the **DNB** project, ensure the following dependencies are available:

### Development Machine Setup
- **MinGW** (Minimalist GNU for Windows)
  - Ensure that `g++` and `make` are installed and accessible via the system’s `PATH`.
- **CMake** (version 3.15 or later)
  - Download from [cmake.org](https://cmake.org/download/).

### Runtime Dependencies for Target Machine
- **Qt6 DLLs**:
  - `Qt6Core.dll`
  - `Qt6Concurrent.dll`
  - `Qt6Xml.dll`
- **CBSDK DLL**:
  - `cbsdk.dll`
- **MinGW Runtime Libraries** (if needed):
  - If the target machine doesn’t have MinGW installed, include runtime DLLs like `libgcc_s_dw2-1.dll` and `libstdc++-6.dll` (only if required by your MinGW setup).

## 2. Build Steps on the Development Machine

### Step 1: Install MinGW and Set Up the Environment
1. Download and install **MinGW** (ensure that `g++`, `gcc`, and `make` are installed).
2. Add MinGW’s `bin` directory to your `PATH` environment variable. Typically, it’s located at `C:\MinGW\bin`.

### Step 2: Install CMake
1. Download and install **CMake** from [cmake.org](https://cmake.org/download/).
2. Add CMake to your `PATH` if not already done during installation.

### Step 3: Set Up the Project Directory
Create the following structure:
