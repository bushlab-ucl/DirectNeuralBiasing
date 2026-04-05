#!/bin/bash
set -e

echo "================================="
echo "Building DNB for Windows x64"
echo "================================="

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf output
mkdir -p output

# Build the Docker image
echo "Building Docker image..."
docker build -t dnb-builder .

# Run the build
echo "Running build in Docker..."
docker run --rm \
    -v "$(pwd)/output:/output" \
    dnb-builder \
    bash -c "cp /app/dnb-release.zip /output/ && echo 'Build artifacts copied to output/'"

# Extract the release
echo "Extracting release..."
cd output
unzip -o dnb-release.zip
rm dnb-release.zip
cd ..

# List the output
echo ""
echo "Build complete! Output files:"
ls -la output/release/

echo ""
echo "To deploy, copy all files from output/release/ to the target Windows machine."