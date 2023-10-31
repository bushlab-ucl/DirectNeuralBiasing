#[no_mangle]
pub extern "C" fn process_data(data: *const i16, length: usize) {
    let data_slice = unsafe { std::slice::from_raw_parts(data, length) };

    // You can now process data_slice as a normal Rust slice.
    // For example, to print the values, you can do:
    for &value in data_slice {
        println!("{}", value);
    }
}
