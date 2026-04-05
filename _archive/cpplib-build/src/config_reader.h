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

  static bool get_save_raw_data(const std::string &config_path)
  {
    Logger::debug("ConfigReader", "Reading save_raw_data flag from: " + config_path);

    std::ifstream inFile(config_path);
    if (!inFile.is_open())
    {
      Logger::warn("ConfigReader", "Could not open config, defaulting save_raw_data to false");
      return false;
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
        auto pos = line.find("save_raw_data:");
        if (pos != std::string::npos)
        {
          std::string value = line.substr(pos + 14);
          value.erase(0, value.find_first_not_of(" \t"));
          value.erase(value.find_last_not_of(" \t\r\n") + 1);
          bool result = (value == "true" || value == "True" || value == "TRUE");
          Logger::info("ConfigReader", "save_raw_data: " + std::string(result ? "true" : "false"));
          return result;
        }
      }
    }
    Logger::info("ConfigReader", "save_raw_data not found, defaulting to false");
    return false;
  }
};

#endif // CONFIG_READER_H