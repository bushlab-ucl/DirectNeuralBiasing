import os
import openai
from collections import defaultdict
import re

# Set your OpenAI API key
openai.api_key = 'YOUR_OPENAI_API_KEY'

# Initialize a dictionary to store module dependencies
module_dependencies = defaultdict(set)

# Define the initial comment detailing what you want ChatGPT to do
initial_comment = """
I'm going to go through a rust module - Direct Neural Biasing - one submodule at a time, and you are going to help me write comments for rustdoc. I will start from the smallest submodules and move up to the larger submodules and eventually the main file - which has four primary submodules: local, processing tests, utils. Use the relevant info you have learned from the submodules to make the documentation of the higher level submodules as clear as possible.

Direct Neural Biasing is a rust package for the closed-loop stimulation of neurons in real time. It is being developed by the Human Electrophysiology lab at UCL, and it is currently in development. It's primarily written in Rust, but has bindings for Python and (soon) C++, to interface with Blackrock Microsystems devices for lab use.

- Processing is the main submodule, it has code for the signal processor, which itself is split up into filters, detectors, and triggers (for now).

- Local and Tests are some helper modules for Rust users.

- Util is a submodule of util functions.

I will copy this intro with each request. Just give me the relevant lines of documentation and where they should be placed. Don't copy out any code. Remember to make the documentation as clear as possible, so that a non-technical python user could understand it.
If any file you recieve is sufficiently documented, just return the existing documentation.
"""

# Function to parse a Rust file for module dependencies
def parse_rust_file(file_path):
    with open(file_path, 'r') as file:
        content = file.read()
        matches = re.findall(r'pub mod (\w+);', content)
        return matches

# Function to recursively collect all modules and their dependencies
def collect_modules(base_dir):
    for root, _, files in os.walk(base_dir):
        for file in files:
            if file.endswith('.rs'):
                file_path = os.path.join(root, file)
                module_name = os.path.relpath(file_path, base_dir).replace(os.sep, '.').replace('.rs', '')
                dependencies = parse_rust_file(file_path)
                for dep in dependencies:
                    dep_module = os.path.join(root, dep).replace(os.sep, '.')
                    module_dependencies[module_name].add(dep_module)

# Function to get modules in leaf-to-root order
def get_leaf_to_root_order():
    ordered_modules = []
    visited = set()

    def visit(module):
        if module not in visited:
            visited.add(module)
            for dep in module_dependencies[module]:
                visit(dep)
            ordered_modules.append(module)

    for module in module_dependencies:
        visit(module)

    return ordered_modules

# Function to submit a module's code to ChatGPT API and get documentation
def submit_module_for_documentation(module_path, module_code):
    response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=f"{initial_comment}\n\n/////\n\n// {module_path}\n\n{module_code}",
        max_tokens=1500,
        temperature=0.7,
    )
    return response.choices[0].text.strip()

# Function to insert documentation into the Rust file
def insert_documentation(file_path, documentation):
    lines = []
    with open(file_path, 'r') as file:
        lines = file.readlines()

    doc_lines = documentation.split('\n')
    new_lines = []
    for line in lines:
        new_lines.append(line)
        if line.strip().startswith('pub mod') or line.strip().startswith('pub struct') or line.strip().startswith('pub trait'):
            new_lines.extend([f"/// {doc_line}\n" for doc_line in doc_lines])
            doc_lines = []

    with open(file_path, 'w') as file:
        file.writelines(new_lines)

# Main script
if __name__ == '__main__':
    base_dir = 'path_to_your_rust_project'  # Replace with the path to your Rust project
    collect_modules(base_dir)
    ordered_modules = get_leaf_to_root_order()

    for module in ordered_modules:
        module_path = module.replace('.', os.sep) + '.rs'
        if os.path.exists(module_path):
            with open(module_path, 'r') as file:
                module_code = file.read()
            documentation = submit_module_for_documentation(module_path, module_code)
            insert_documentation(module_path, documentation)
            print(f"Documentation added for {module}")
