# Direct Neural Biasing
 
### WIP - Rust/C++/Python code for Closed Loop Stimulation project in HEL

#### Curent State of Project:

- src/Rustlib - Rust code for functions. This is where the business logic lives and will live.
- src/Pythonlib - Python code for importing rust dnb module functions for python work. Pulls exposed functions from src/Rustlib 
- src/Cpplib - C++ code for interfacing with Blackrock NSP system and NPlay. Pulls 'extern c' functions from src/Rustlib 

#### Some Other Bits:

Rust DNB Server: Generates a sample LFP signal and occasional Interictal spikes and SWRs. Streams to :8080.
Rust DNB Client: Listens to port 8080 and outputs signal to terminal.
Rust DNB Filters: Implementation of Butterworth, Chebyshev, Bimodal filters
Python DNB Module: Python wrapper for running rust DNB filters (WIP)
Python Scipy Tests: Test routines for comparing rust DNB filters witrh relevant scipy filters (TODO)
Python Optimisiation Scripts: Routines for generating optimal filter/module coeffecients for data (TODO)
