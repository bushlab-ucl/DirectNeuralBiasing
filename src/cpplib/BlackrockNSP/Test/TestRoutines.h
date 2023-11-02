#pragma once
#include <windows.h>

extern "C"
{
  typedef void(__cdecl *ProcessDataFunc)(const INT16 *, size_t);
  typedef void(__cdecl *ProcessDataComplexFunc)(INT16 *, size_t);
}

class TestRoutines
{
public:
  TestRoutines();
  ~TestRoutines();

  bool loadRustLibrary();
  void unloadRustLibrary();

  static void process_data_cpp(INT16 *data, size_t length);
  static void process_data_complex_cpp(INT16 *data, size_t length);

  void process_data_rust(const INT16 *data, size_t length);
  void process_data_complex_rust(INT16 *data, size_t length);

  static void RunTestRoutines(TestRoutines &testRoutines, INT16 *data, size_t length);

private:
  HINSTANCE hinstLib;
  ProcessDataFunc process_data_rust_func;
  ProcessDataComplexFunc process_data_complex_rust_func;
};
