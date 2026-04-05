#include "../include/signal_processor.h"
#include <iostream>
#include <vector>
#include <string>

int main() {
    // Create a signal processor from config
    const char* config_path = "config/config.yaml";
    void* processor = create_signal_processor_from_config(config_path);
    
    if (!processor) {
        std::cerr << "Failed to create signal processor" << std::endl;
        return 1;
    }

    // Log some messages from C++ code
    log_message(processor, "C++: Starting signal processing");
    log_message(processor, "C++: Channel changed to 1");
    log_message(processor, "C++: Wait time set to 100ms");
    
    // Simulate some processing
    std::vector<double> test_data(1000, 0.1);
    
    // Log before processing
    log_message(processor, "C++: Processing chunk of 1000 samples");
    
    // Process the data
    void* trigger_result = run_chunk(processor, test_data.data(), test_data.size());
    
    if (trigger_result) {
        double trigger_timestamp = *(double*)trigger_result;
        std::string trigger_msg = "C++: Trigger detected at timestamp: " + std::to_string(trigger_timestamp);
        log_message(processor, trigger_msg.c_str());
        
        // Free the trigger result
        delete (double*)trigger_result;
    } else {
        log_message(processor, "C++: No trigger detected in this chunk");
    }
    
    // Log completion
    log_message(processor, "C++: Processing completed");
    
    // Clean up
    delete_signal_processor(processor);
    
    return 0;
} 