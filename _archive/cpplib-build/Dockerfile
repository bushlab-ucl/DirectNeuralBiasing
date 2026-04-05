# Use the dockcross Windows cross-compilation image
FROM dockcross/windows-shared-x64:latest

# Install additional dependencies
RUN apt-get update && apt-get install -y \
    cmake \
    zip \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy the CereLink SDK
COPY Cerelink/CBSDK-7.6.1-win64 /opt/cbsdk

# Copy source files
COPY src/ /app/src/
COPY CMakeLists.txt /app/

# Copy resources
COPY resources/ /app/resources/

# Create build directory
RUN mkdir -p /app/build

# Configure and build
WORKDIR /app/build
RUN cmake .. \
    -DCMAKE_TOOLCHAIN_FILE=/usr/src/mxe/usr/x86_64-w64-mingw32.shared/share/cmake/mxe-conf.cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DCBSDK_PATH=/opt/cbsdk

RUN make -j$(nproc)

# Create release package
RUN mkdir -p /app/release && \
    cp DNB.exe /app/release/ && \
    cp /opt/cbsdk/bin/*.dll /app/release/ && \
    cp /app/resources/* /app/release/

# Create output directory structure
RUN cd /app && zip -r dnb-release.zip release/