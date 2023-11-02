mod filters;

#[cfg(not(feature = "python-extension"))]
mod client;
#[cfg(not(feature = "python-extension"))]
mod server;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() > 1 {
        match args[1].as_str() {
            "client" => client::run().unwrap(),
            "server" => server::run().unwrap(),
            _ => println!("Invalid argument, please use 'client' or 'server'"),
        }
    } else {
        println!("Please specify 'client' or 'server' as argument");
    }
}
