#include "TestRoutines.h"
#include <iostream>
#include <chrono>
#include <vector>

void TestRoutines::RunTestRoutines(TestRoutines &testRoutines, INT16 *data, size_t length)
{
  auto start = std::chrono::high_resolution_clock::now();
  auto end = start;

  // Run C++ processing functions
  start = std::chrono::high_resolution_clock::now();
  TestRoutines::process_data_cpp(data, length);
  end = std::chrono::high_resolution_clock::now();
  std::cout << "Time elapsed in C++ process_data() function: "
            << std::chrono::duration_cast<std::chrono::microseconds>(end - start).count()
            << " microseconds" << std::endl;

  start = std::chrono::high_resolution_clock::now();
  TestRoutines::process_data_complex_cpp(data, length);
  end = std::chrono::high_resolution_clock::now();
  std::cout << "Time elapsed in C++ complex_process_data() function: "
            << std::chrono::duration_cast<std::chrono::microseconds>(end - start).count()
            << " microseconds" << std::endl;

  // Run Rust processing functions
  start = std::chrono::high_resolution_clock::now();
  testRoutines.process_data_rust(data, length);
  end = std::chrono::high_resolution_clock::now();
  std::cout << "Time elapsed in Rust process_data() function: "
            << std::chrono::duration_cast<std::chrono::microseconds>(end - start).count()
            << " microseconds" << std::endl;

  start = std::chrono::high_resolution_clock::now();
  testRoutines.process_data_complex_rust(data, length);
  end = std::chrono::high_resolution_clock::now();
  std::cout << "Time elapsed in Rust complex_process_data() function: "
            << std::chrono::duration_cast<std::chrono::microseconds>(end - start).count()
            << " microseconds" << std::endl;
}

TestRoutines::TestRoutines() : hinstLib(NULL), process_data_rust_func(NULL), process_data_complex_rust_func(NULL)
{
}

TestRoutines::~TestRoutines()
{
  unloadRustLibrary();
}

bool TestRoutines::loadRustLibrary()
{
  hinstLib = LoadLibrary(TEXT("..\\..\\rustlib\\target\\release\\direct_neural_biasing.dll"));
  if (!hinstLib)
  {
    std::cerr << "DLL failed to load! - from test routines" << std::endl;
    return false;
  }

  process_data_rust_func = (ProcessDataFunc)GetProcAddress(hinstLib, "process_data");
  if (!process_data_rust_func)
  {
    std::cerr << "Rust process_data function not found!" << std::endl;
    FreeLibrary(hinstLib);
    return false;
  }

  process_data_complex_rust_func = (ProcessDataComplexFunc)GetProcAddress(hinstLib, "process_data_complex");
  if (!process_data_complex_rust_func)
  {
    std::cerr << "Rust process_data_complex function not found!" << std::endl;
    FreeLibrary(hinstLib);
    return false;
  }

  return true;
}

void TestRoutines::unloadRustLibrary()
{
  if (hinstLib)
  {
    FreeLibrary(hinstLib);
    hinstLib = NULL;
  }
}

void TestRoutines::process_data_rust(const INT16 *data, size_t length)
{
  if (process_data_rust_func)
  {
    process_data_rust_func(data, length);
  }
  else
  {
    std::cerr << "Rust process_data function not loaded!" << std::endl;
  }
}

void TestRoutines::process_data_complex_rust(INT16 *data, size_t length)
{
  if (process_data_complex_rust_func)
  {
    process_data_complex_rust_func(data, length);
  }
  else
  {
    std::cerr << "Rust process_data_complex function not loaded!" << std::endl;
  }
}

extern "C" void TestRoutines::process_data_cpp(INT16 *data, size_t length)
{
  for (size_t i = 0; i < length; ++i)
  {
    data[i] += 1;
  }
}

extern "C" void TestRoutines::process_data_complex_cpp(INT16 *data, size_t length)
{
  static const INT16 kernel[] = {1, 2, 3, 2, 1};
  static const size_t kernel_size = 5;

  std::vector<INT16> result(length, 0);

  INT16 *result_ptr = result.data();
  const INT16 *data_end = data + length;
  const INT16 *kernel_end = kernel + kernel_size;

  for (const INT16 *data_ptr = data; data_ptr != data_end; ++data_ptr, ++result_ptr)
  {
    INT16 sum = 0;
    const INT16 *k_ptr = kernel;
    const INT16 *d_ptr = data_ptr;

    while (k_ptr != kernel_end && d_ptr != data_end)
    {
      sum += (*d_ptr) * (*k_ptr);
      ++d_ptr;
      ++k_ptr;
    }

    *result_ptr = sum;
  }

  std::copy(result.begin(), result.end(), data);
}
