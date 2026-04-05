#ifndef BUFFER_MANAGER_H
#define BUFFER_MANAGER_H

#include <mutex>
#include <condition_variable>
#include "logger.h"

const size_t BUFFER_SIZE = 4096;
const size_t NUM_BUFFERS = 2;

struct Buffer
{
  double data[BUFFER_SIZE];
  bool ready = false;
};

class BufferManager
{
private:
  Buffer buffers[NUM_BUFFERS];
  size_t filling_buffer_index = 0;
  std::mutex buffer_mutex;
  std::condition_variable buffer_cv;
  bool stop_processing = false;

public:
  BufferManager()
  {
    Logger::info("BufferManager", "Initialized with " + std::to_string(NUM_BUFFERS) +
                                      " buffers of size " + std::to_string(BUFFER_SIZE));
  }

  // Fill a buffer with data (called by acquisition thread)
  bool fill_buffer(const double *data, size_t length)
  {
    if (length > BUFFER_SIZE)
    {
      Logger::error("BufferManager", "Chunk size exceeds buffer size");
      return false;
    }

    // Wait for an available buffer
    {
      std::unique_lock<std::mutex> lock(buffer_mutex);
      buffer_cv.wait(lock, [this]()
                     { return !buffers[filling_buffer_index].ready || stop_processing; });

      if (stop_processing)
      {
        Logger::debug("BufferManager", "Stop signal received during fill");
        return false;
      }
    }

    // Copy data to buffer
    std::copy(data, data + length, buffers[filling_buffer_index].data);

    // Mark buffer as ready and switch to next buffer
    {
      std::lock_guard<std::mutex> lock(buffer_mutex);
      buffers[filling_buffer_index].ready = true;
      filling_buffer_index = (filling_buffer_index + 1) % NUM_BUFFERS;
    }
    buffer_cv.notify_one();

    return true;
  }

  // Get a buffer for processing (called by processing thread)
  bool get_ready_buffer(size_t &buffer_index)
  {
    std::unique_lock<std::mutex> lock(buffer_mutex);
    buffer_cv.wait(lock, [this]()
                   { return stop_processing || buffers[0].ready || buffers[1].ready; });

    if (stop_processing)
    {
      Logger::debug("BufferManager", "Stop signal received during get");
      return false;
    }

    buffer_index = buffers[0].ready ? 0 : 1;
    buffers[buffer_index].ready = false;
    return true;
  }

  // Get pointer to buffer data
  const double *get_buffer_data(size_t buffer_index) const
  {
    return buffers[buffer_index].data;
  }

  // Signal processing complete for a buffer
  void release_buffer()
  {
    buffer_cv.notify_one();
  }

  // Stop all buffer operations
  void stop()
  {
    Logger::info("BufferManager", "Stopping buffer operations");
    stop_processing = true;
    buffer_cv.notify_all();
  }

  bool is_stopped() const
  {
    return stop_processing;
  }
};

#endif // BUFFER_MANAGER_H