# Direct Neural Biasing
 
### WIP - Rust/C++/Python code for Closed Loop Stimulation project in HEL

#### Curent State of Project:

- **src/rustlib** - Rust code for functions. This is where the business logic lives and will live.
- **src/pythonlib** - Python code for importing rust dnb module functions for python work. Pulls exposed functions from src/Rustlib 
- **src/cpplib** - C++ code for interfacing with Blackrock NSP system and NPlay. Pulls 'extern c' functions from src/Rustlib 

#### Some Other Loose Bits:

- **Rust DNB Server (rustlib)** - Generates a sample LFP signal and occasional Interictal spikes and SWRs. Streams to :8080.
- **Rust DNB Client (rustlib)** - Listens to port 8080 and outputs signal to terminal.
- **Rust DNB Filters (rustlib)** - Implementation of Butterworth, Chebyshev, Bimodal filters
- **Python DNB Module (rustlib)** - Python wrapper for running rust DNB filters (WIP)
--- 
- **Python Scipy Tests (pythonlib)** - Test routines for comparing rust DNB filters witrh relevant scipy filters (TODO)
- **Python Optimisiation Scripts (pythonlib)** - Routines for generating optimal filter/module coeffecients for data (TODO)
--- 
- **BlackrockNSP (cpplib)** - Visual studio project for connecting to realtime NSP/NPlay stream to run DNB closed-loop code.
