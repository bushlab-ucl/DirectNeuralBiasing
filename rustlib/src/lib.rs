se std::slice;

#[no_mangle]
pub extern "C" fn process_data(data: *mut i16, length: usize) {
    let slice = unsafe { std::slice::from_raw_parts_mut(data, length) };
    for num in slice {
        *num += 1; // example modification
    }
}

#[no_mangle]
pub extern "C" fn process_data_complex(data: *mut i16, length: usize) {
    let slice = unsafe { std::slice::from_raw_parts_mut(data, length) };
    let kernel = [1, 2, 3, 2, 1];
    let result = convolution(slice, &kernel);
    slice.copy_from_slice(&result);
}

fn convolution(data: &[i16], kernel: &[i16]) -> Vec<i16> {
    let k_len = kernel.len();
    let d_len = data.len();
    let mut result = vec![0; d_len];

    for i in 0..d_len {
        let mut sum = 0;
        for j in 0..k_len {
            if i + j < d_len {
                sum += data[i + j] * kernel[j];
            }
        }
        result[i] = sum;
    }

    result
}
