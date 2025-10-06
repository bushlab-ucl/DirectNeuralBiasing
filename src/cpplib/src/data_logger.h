#ifndef DATA_LOGGER_H
#define DATA_LOGGER_H

#include <queue>
#include <vector>
#include <fstream>
#include <mutex>
#include <condition_variable>
#include <thread>
#include <chrono>
#include <sstream>
#include <windows.h>
#include "logger.h"

class DataLogger
{
private:
  struct LogChunk
  {
    std::vector<double> data;
  };

  std::queue<LogChunk> log_queue;
  std::mutex queue_mutex;
  std::condition_variable queue_cv;
  bool stop_logging = false;
  bool enabled = false;
  std::thread logging_thread;
  const size_t MAX_QUEUE_SIZE = 1000;

  void logging_loop(const std::string &filename)
  {
    Logger::info("DataLogger", "Starting logging thread for: " + filename);

    std::ofstream outfile(filename, std::ios::binary);
    if (!outfile.is_open())
    {
      Logger::error("DataLogger", "Failed to open log file: " + filename);
      stop_logging = true;
      return;
    }

    size_t total_samples_written = 0;
    size_t chunks_written = 0;

    while (true)
    {
      LogChunk chunk;

      {
        std::unique_lock<std::mutex> lock(queue_mutex);
        queue_cv.wait(lock, [this]()
                      { return stop_logging || !log_queue.empty(); });

        if (log_queue.empty())
        {
          if (stop_logging)
            break;
          else
            continue;
        }

        chunk = std::move(log_queue.front());
        log_queue.pop();

        if (log_queue.size() < MAX_QUEUE_SIZE)
        {
          queue_cv.notify_all();
        }
      }

      if (!chunk.data.empty())
      {
        outfile.write(reinterpret_cast<const char *>(chunk.data.data()),
                      chunk.data.size() * sizeof(double));
        total_samples_written += chunk.data.size();
        chunks_written++;

        if (chunks_written % 1000 == 0)
        {
          std::ostringstream oss;
          oss << "Logged " << chunks_written << " chunks ("
              << (total_samples_written / 30000.0) << " seconds)";
          Logger::debug("DataLogger", oss.str());
        }
      }
    }

    outfile.close();
    std::ostringstream oss;
    oss << "Logging stopped. Total samples: " << total_samples_written
        << " (" << (total_samples_written / 30000.0) << " seconds)";
    Logger::info("DataLogger", oss.str());
  }

  static std::string generate_filename(int channel)
  {
    CreateDirectoryA("./data", NULL);

    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    char time_str[100];
    std::strftime(time_str, sizeof(time_str), "%Y%m%d_%H%M%S", std::localtime(&time_t));

    std::ostringstream oss;
    oss << "./data/raw_data_ch" << channel << "_" << time_str << ".bin";
    return oss.str();
  }

public:
  void start(int channel)
  {
    if (!enabled)
    {
      Logger::info("DataLogger", "Data logging is disabled");
      return;
    }

    std::string filename = generate_filename(channel);
    Logger::info("DataLogger", "Starting data logging to: " + filename);
    logging_thread = std::thread(&DataLogger::logging_loop, this, filename);
  }

  void log_chunk(const double *data, size_t length)
  {
    if (!enabled)
      return;

    std::unique_lock<std::mutex> lock(queue_mutex);

    if (log_queue.size() >= MAX_QUEUE_SIZE)
    {
      static bool warned = false;
      if (!warned)
      {
        Logger::warn("DataLogger", "Queue full (" + std::to_string(MAX_QUEUE_SIZE) +
                                       " chunks). Waiting for disk I/O...");
        warned = true;
      }

      queue_cv.wait_for(lock, std::chrono::milliseconds(100), [this]()
                        { return log_queue.size() < MAX_QUEUE_SIZE || stop_logging; });

      if (stop_logging)
        return;
    }

    LogChunk chunk;
    chunk.data.assign(data, data + length);
    log_queue.push(std::move(chunk));
    queue_cv.notify_one();
  }

  void stop()
  {
    if (!enabled)
      return;

    Logger::info("DataLogger", "Stopping data logger...");
    {
      std::lock_guard<std::mutex> lock(queue_mutex);
      Logger::debug("DataLogger", "Queue size at shutdown: " + std::to_string(log_queue.size()));
    }

    stop_logging = true;
    queue_cv.notify_all();

    if (logging_thread.joinable())
    {
      logging_thread.join();
    }
    Logger::info("DataLogger", "Data logger stopped");
  }

  void set_enabled(bool enable)
  {
    enabled = enable;
  }

  bool is_enabled() const
  {
    return enabled;
  }
};

#endif // DATA_LOGGER_H