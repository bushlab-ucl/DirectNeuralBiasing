mod local;
mod processing;
mod tests;
mod utils;

/// - For running the local debug.
#[cfg(not(feature = "python-extension"))]
pub fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 {
        match args[1].as_str() {
            "client" => local::client::run().unwrap(),
            "server" => local::server::run().unwrap(),
            _ => println!("Invalid argument, please use 'client' or 'server'"),
        }
    } else {
        println!("Please specify 'client' or 'server' as argument");
    }
}
