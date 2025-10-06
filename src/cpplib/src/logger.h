#ifndef LOGGER_H
#define LOGGER_H

#include <iostream>
#include <fstream>
#include <string>
#include <chrono>
#include <iomanip>
#include <sstream>
#include <mutex>

class Logger
{
private:
  static std::ofstream log_file;
  static std::mutex log_mutex;
  static bool initialized;

  static std::string get_timestamp()
  {
    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                  now.time_since_epoch()) %
              1000;

    char buffer[100];
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", std::localtime(&time_t));

    std::ostringstream oss;
    oss << buffer << '.' << std::setfill('0') << std::setw(3) << ms.count();
    return oss.str();
  }

public:
  static void init(const std::string &filename = "")
  {
    std::lock_guard<std::mutex> lock(log_mutex);
    CreateDirectoryA("./logs", NULL);

    std::string actual_filename = filename;
    if (actual_filename.empty())
    {
      // Generate timestamp-based filename
      auto now = std::chrono::system_clock::now();
      auto time_t = std::chrono::system_clock::to_time_t(now);
      char time_str[100];
      std::strftime(time_str, sizeof(time_str), "%Y%m%d_%H%M%S", std::localtime(&time_t));
      actual_filename = "logs/cpp_debug_" + std::string(time_str) + ".log";
    }

    log_file.open(actual_filename, std::ios::out | std::ios::app);
    initialized = log_file.is_open();

    if (initialized)
    {
      std::cout << "Debug logging to: " << actual_filename << std::endl;
    }
  }

  static void log(const std::string &level, const std::string &component,
                  const std::string &message)
  {
    std::lock_guard<std::mutex> lock(log_mutex);
    std::string timestamp = get_timestamp();
    std::string log_line = "[" + timestamp + "] [" + level + "] [" + component + "] " + message;

    // Always print to console
    std::cout << log_line << std::endl;

    // Write to file if initialized
    if (initialized && log_file.is_open())
    {
      log_file << log_line << std::endl;
      log_file.flush();
    }
  }

  static void info(const std::string &component, const std::string &message)
  {
    log("INFO", component, message);
  }

  static void warn(const std::string &component, const std::string &message)
  {
    log("WARN", component, message);
  }

  static void error(const std::string &component, const std::string &message)
  {
    log("ERROR", component, message);
  }

  static void debug(const std::string &component, const std::string &message)
  {
    log("DEBUG", component, message);
  }

  static void close()
  {
    std::lock_guard<std::mutex> lock(log_mutex);
    if (log_file.is_open())
    {
      log_file.close();
    }
  }
};

// Static member initialization
std::ofstream Logger::log_file;
std::mutex Logger::log_mutex;
bool Logger::initialized = false;

#endif // LOGGER_H