mod config;
mod local;
mod processing;
mod tests;
mod utils;
mod visualization;

/// - For running the local debug.
// #[cfg(not(feature = "python-extension"))]
pub fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 {
        match args[1].as_str() {
            "local" => local::process_file::run().unwrap(), // true to process whole file
            _ => println!("Invalid argument, please use 'client', 'server', or 'local'"),
        }
    } else {
        println!("Please specify 'client' or 'server' as argument");
    }
}
