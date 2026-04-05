#ifndef CONFIG_READER_H
#define CONFIG_READER_H

#include <fstream>
#include <string>
#include <iostream>
#include "logger.h"

class ConfigReader
{
public:
  static int get_channel(const std::string &config_path)
  {
    Logger::debug("ConfigReader", "Reading channel from: " + config_path);

    std::ifstream inFile(config_path);
    if (!inFile.is_open())
    {
      Logger::error("ConfigReader", "Failed to open " + config_path);
      return -1;
    }

    std::string line;
    bool in_processor_block = false;
    while (std::getline(inFile, line))
    {
      if (line.find("processor:") != std::string::npos)
      {
        in_processor_block = true;
        continue;
      }
      if (in_processor_block)
      {
        if (line.find(':') != std::string::npos &&
            line.find_first_not_of(" \t") != std::string::npos &&
            line[0] != ' ' && line[0] != '\t')
        {
          break;
        }
        auto pos = line.find("channel:");
        if (pos != std::string::npos)
        {
          std::string num = line.substr(pos + 8);
          try
          {
            int channel = std::stoi(num);
            Logger::info("ConfigReader", "Channel: " + std::to_string(channel));
            return channel;
          }
          catch (...)
          {
            Logger::error("ConfigReader", "Failed to parse channel number");
            return -1;
          }
        }
      }
    }
    Logger::error("ConfigReader", "No channel entry found in config");
    return -1;
  }

  static int get_setup_sleep_ms(const std::string &config_path)
  {
    Logger::debug("ConfigReader", "Reading setup_sleep_ms from: " + config_path);

    std::ifstream inFile(config_path);
    if (!inFile.is_open())
    {
      Logger::error("ConfigReader", "Failed to open " + config_path);
      return -1;
    }

    std::string line;
    bool in_processor_block = false;
    while (std::getline(inFile, line))
    {
      if (line.find("processor:") != std::string::npos)
      {
        in_processor_block = true;
        continue;
      }
      if (in_processor_block)
      {
        if (line.find(':') != std::string::npos &&
            line.find_first_not_of(" \t") != std::string::npos &&
            line[0] != ' ' && line[0] != '\t')
        {
          break;
        }
        auto pos = line.find("setup_sleep_ms:");
        if (pos != std::string::npos)
        {
          std::string num = line.substr(pos + 15);
          try
          {
            int sleep_ms = std::stoi(num);
            Logger::info("ConfigReader", "setup_sleep_ms: " + std::to_string(sleep_ms));
            return sleep_ms;
          }
          catch (...)
          {
            Logger::error("ConfigReader", "Failed to parse setup_sleep_ms number");
            return -1;
          }
        }
      }
    }
    Logger::error("ConfigReader", "No setup_sleep_ms entry found in config");
    return -1;
  }
};

#endif // CONFIG_READER_H