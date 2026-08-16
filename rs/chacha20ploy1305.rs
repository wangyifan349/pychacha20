/*!
This script implements the IETF ChaCha20-Poly1305 AEAD construction defined in RFC 8439 entirely in Rust and provides an interactive CLI for in-place encryption and decryption of a single file or all files in a directory recursively. The ChaCha20 and Poly1305 primitives are implemented directly in this file, while the Rust standard library is used only for filesystem operations and random nonce generation. File names and directory structure are preserved. Each encrypted file uses an independently generated 96-bit nonce and is stored as nonce || authentication tag || ciphertext; the CLI file-processing path uses empty associated data (AAD).
*/
#[cfg(windows)]
use std::ffi::c_void;
use std::fs::{self, OpenOptions};
#[cfg(unix)]
use std::fs::File;
use std::io::{self, Write};
#[cfg(unix)]
use std::io::Read;
use std::path::{Path, PathBuf};

const UINT32_MASK: u64 = 0xFFFF_FFFF;
const CHACHA20_BLOCK_SIZE: usize = 64;
const NONCE_SIZE: usize = 12;
const TAG_SIZE: usize = 16;
const KEY_SIZE: usize = 32;
const LIMB_MASK: u64 = 0x03FF_FFFF;

#[cfg(windows)]
#[link(name = "bcrypt")]
extern "system" {
    #[link_name = "BCryptGenRandom"]
    fn bcrypt_generate_random(algorithm: *mut c_void, buffer: *mut u8, buffer_length: u32, flags: u32) -> i32;
}

#[cfg(windows)]
#[link(name = "kernel32")]
extern "system" {
    #[link_name = "MoveFileExW"]
    fn move_file_replace_existing_wide(existing_file_name: *const u16, new_file_name: *const u16, flags: u32) -> i32;
}

#[cfg(windows)]
const BCRYPT_USE_SYSTEM_PREFERRED_RNG: u32 = 0x0000_0002;
#[cfg(windows)]
const MOVEFILE_REPLACE_EXISTING: u32 = 0x0000_0001;

type ApplicationResult<T> = Result<T, String>;

#[derive(Clone, Copy)]
enum OperationMode {
    Encrypt,
    Decrypt,
}

fn load_little_endian_u32(data: &[u8], offset: usize) -> u32 {
    u32::from_le_bytes([data[offset], data[offset + 1], data[offset + 2], data[offset + 3]])
}

fn quarter_round(state: &mut [u32; 16], first: usize, second: usize, third: usize, fourth: usize) {
    state[first] = state[first].wrapping_add(state[second]);
    state[fourth] ^= state[first];
    state[fourth] = state[fourth].rotate_left(16);
    state[third] = state[third].wrapping_add(state[fourth]);
    state[second] ^= state[third];
    state[second] = state[second].rotate_left(12);
    state[first] = state[first].wrapping_add(state[second]);
    state[fourth] ^= state[first];
    state[fourth] = state[fourth].rotate_left(8);
    state[third] = state[third].wrapping_add(state[fourth]);
    state[second] ^= state[third];
    state[second] = state[second].rotate_left(7);
}

fn chacha20_block(key: &[u8], counter: u64, nonce: &[u8]) -> ApplicationResult<[u8; CHACHA20_BLOCK_SIZE]> {
    if key.len() != KEY_SIZE || nonce.len() != NONCE_SIZE {
        return Err("ChaCha20 requires a 32-byte key and 12-byte nonce".to_string());
    }
    if counter > UINT32_MASK {
        return Err("counter must be a 32-bit unsigned integer".to_string());
    }
    let constants = b"expand 32-byte k";
    let mut state = [0u32; 16];
    for index in 0..4 {
        state[index] = load_little_endian_u32(constants, index * 4);
    }
    for index in 0..8 {
        state[4 + index] = load_little_endian_u32(key, index * 4);
    }
    state[12] = counter as u32;
    for index in 0..3 {
        state[13 + index] = load_little_endian_u32(nonce, index * 4);
    }
    let mut working_state = state;
    for _ in 0..10 {
        quarter_round(&mut working_state, 0, 4, 8, 12);
        quarter_round(&mut working_state, 1, 5, 9, 13);
        quarter_round(&mut working_state, 2, 6, 10, 14);
        quarter_round(&mut working_state, 3, 7, 11, 15);
        quarter_round(&mut working_state, 0, 5, 10, 15);
        quarter_round(&mut working_state, 1, 6, 11, 12);
        quarter_round(&mut working_state, 2, 7, 8, 13);
        quarter_round(&mut working_state, 3, 4, 9, 14);
    }
    let mut output = [0u8; CHACHA20_BLOCK_SIZE];
    for index in 0..16 {
        let word = working_state[index].wrapping_add(state[index]).to_le_bytes();
        output[index * 4..index * 4 + 4].copy_from_slice(&word);
    }
    Ok(output)
}

fn chacha20_xor(key: &[u8], nonce: &[u8], counter: u64, data: &[u8]) -> ApplicationResult<Vec<u8>> {
    if key.len() != KEY_SIZE || nonce.len() != NONCE_SIZE {
        return Err("ChaCha20 requires a 32-byte key and 12-byte nonce".to_string());
    }
    if counter > UINT32_MASK {
        return Err("counter must be a 32-bit unsigned integer".to_string());
    }
    let block_count = ((data.len() as u64) + 63) / 64;
    match counter.checked_add(block_count) {
        Some(value) if value <= (1u64 << 32) => {}
        _ => return Err("ChaCha20 counter overflow".to_string()),
    }
    let mut output = vec![0u8; data.len()];
    for block_index in 0..block_count {
        let keystream = chacha20_block(key, counter + block_index, nonce)?;
        let block_offset = block_index as usize * CHACHA20_BLOCK_SIZE;
        let block_end = usize::min(block_offset + CHACHA20_BLOCK_SIZE, data.len());
        for byte_index in 0..(block_end - block_offset) {
            output[block_offset + byte_index] = data[block_offset + byte_index] ^ keystream[byte_index];
        }
    }
    Ok(output)
}

fn poly1305_mac(message: &[u8], one_time_key: &[u8]) -> ApplicationResult<[u8; TAG_SIZE]> {
    if one_time_key.len() != KEY_SIZE {
        return Err("Poly1305 requires a 32-byte one-time key".to_string());
    }
    let multiplier_limb_zero = (load_little_endian_u32(one_time_key, 0) as u64) & 0x03FF_FFFF;
    let multiplier_limb_one = ((load_little_endian_u32(one_time_key, 3) as u64) >> 2) & 0x03FF_FF03;
    let multiplier_limb_two = ((load_little_endian_u32(one_time_key, 6) as u64) >> 4) & 0x03FF_C0FF;
    let multiplier_limb_three = ((load_little_endian_u32(one_time_key, 9) as u64) >> 6) & 0x03F0_3FFF;
    let multiplier_limb_four = ((load_little_endian_u32(one_time_key, 12) as u64) >> 8) & 0x000F_FFFF;
    let multiplier_limb_one_times_five = multiplier_limb_one * 5;
    let multiplier_limb_two_times_five = multiplier_limb_two * 5;
    let multiplier_limb_three_times_five = multiplier_limb_three * 5;
    let multiplier_limb_four_times_five = multiplier_limb_four * 5;
    let (mut accumulator_limb_zero, mut accumulator_limb_one, mut accumulator_limb_two, mut accumulator_limb_three, mut accumulator_limb_four) = (0u64, 0u64, 0u64, 0u64, 0u64);

    for chunk in message.chunks(16) {
        let mut block = [0u8; 16];
        block[..chunk.len()].copy_from_slice(chunk);
        let appended_one_bit = if chunk.len() == 16 {
            1u64 << 24
        } else {
            block[chunk.len()] = 1;
            0
        };
        let message_word_zero = load_little_endian_u32(&block, 0) as u64;
        let message_word_one = load_little_endian_u32(&block, 4) as u64;
        let message_word_two = load_little_endian_u32(&block, 8) as u64;
        let message_word_three = load_little_endian_u32(&block, 12) as u64;
        accumulator_limb_zero += message_word_zero & LIMB_MASK;
        accumulator_limb_one += ((message_word_zero >> 26) | (message_word_one << 6)) & LIMB_MASK;
        accumulator_limb_two += ((message_word_one >> 20) | (message_word_two << 12)) & LIMB_MASK;
        accumulator_limb_three += ((message_word_two >> 14) | (message_word_three << 18)) & LIMB_MASK;
        accumulator_limb_four += (message_word_three >> 8) | appended_one_bit;

        let product_limb_zero = accumulator_limb_zero * multiplier_limb_zero + accumulator_limb_one * multiplier_limb_four_times_five + accumulator_limb_two * multiplier_limb_three_times_five + accumulator_limb_three * multiplier_limb_two_times_five + accumulator_limb_four * multiplier_limb_one_times_five;
        let mut product_limb_one = accumulator_limb_zero * multiplier_limb_one + accumulator_limb_one * multiplier_limb_zero + accumulator_limb_two * multiplier_limb_four_times_five + accumulator_limb_three * multiplier_limb_three_times_five + accumulator_limb_four * multiplier_limb_two_times_five;
        let mut product_limb_two = accumulator_limb_zero * multiplier_limb_two + accumulator_limb_one * multiplier_limb_one + accumulator_limb_two * multiplier_limb_zero + accumulator_limb_three * multiplier_limb_four_times_five + accumulator_limb_four * multiplier_limb_three_times_five;
        let mut product_limb_three = accumulator_limb_zero * multiplier_limb_three + accumulator_limb_one * multiplier_limb_two + accumulator_limb_two * multiplier_limb_one + accumulator_limb_three * multiplier_limb_zero + accumulator_limb_four * multiplier_limb_four_times_five;
        let mut product_limb_four = accumulator_limb_zero * multiplier_limb_four + accumulator_limb_one * multiplier_limb_three + accumulator_limb_two * multiplier_limb_two + accumulator_limb_three * multiplier_limb_one + accumulator_limb_four * multiplier_limb_zero;

        let mut carry = product_limb_zero >> 26;
        accumulator_limb_zero = product_limb_zero & LIMB_MASK;
        product_limb_one += carry;
        carry = product_limb_one >> 26;
        accumulator_limb_one = product_limb_one & LIMB_MASK;
        product_limb_two += carry;
        carry = product_limb_two >> 26;
        accumulator_limb_two = product_limb_two & LIMB_MASK;
        product_limb_three += carry;
        carry = product_limb_three >> 26;
        accumulator_limb_three = product_limb_three & LIMB_MASK;
        product_limb_four += carry;
        carry = product_limb_four >> 26;
        accumulator_limb_four = product_limb_four & LIMB_MASK;
        accumulator_limb_zero += carry * 5;
        carry = accumulator_limb_zero >> 26;
        accumulator_limb_zero &= LIMB_MASK;
        accumulator_limb_one += carry;
    }

    let mut carry = accumulator_limb_one >> 26;
    accumulator_limb_one &= LIMB_MASK;
    accumulator_limb_two += carry;
    carry = accumulator_limb_two >> 26;
    accumulator_limb_two &= LIMB_MASK;
    accumulator_limb_three += carry;
    carry = accumulator_limb_three >> 26;
    accumulator_limb_three &= LIMB_MASK;
    accumulator_limb_four += carry;
    carry = accumulator_limb_four >> 26;
    accumulator_limb_four &= LIMB_MASK;
    accumulator_limb_zero += carry * 5;
    carry = accumulator_limb_zero >> 26;
    accumulator_limb_zero &= LIMB_MASK;
    accumulator_limb_one += carry;

    let mut reduced_limb_zero = accumulator_limb_zero + 5;
    carry = reduced_limb_zero >> 26;
    reduced_limb_zero &= LIMB_MASK;
    let mut reduced_limb_one = accumulator_limb_one + carry;
    carry = reduced_limb_one >> 26;
    reduced_limb_one &= LIMB_MASK;
    let mut reduced_limb_two = accumulator_limb_two + carry;
    carry = reduced_limb_two >> 26;
    reduced_limb_two &= LIMB_MASK;
    let mut reduced_limb_three = accumulator_limb_three + carry;
    carry = reduced_limb_three >> 26;
    reduced_limb_three &= LIMB_MASK;
    let reduced_limb_four = (accumulator_limb_four + carry).wrapping_sub(1u64 << 26);
    let use_reduced_mask = (reduced_limb_four >> 63).wrapping_sub(1);
    let use_original_mask = !use_reduced_mask;
    accumulator_limb_zero = (accumulator_limb_zero & use_original_mask) | (reduced_limb_zero & use_reduced_mask);
    accumulator_limb_one = (accumulator_limb_one & use_original_mask) | (reduced_limb_one & use_reduced_mask);
    accumulator_limb_two = (accumulator_limb_two & use_original_mask) | (reduced_limb_two & use_reduced_mask);
    accumulator_limb_three = (accumulator_limb_three & use_original_mask) | (reduced_limb_three & use_reduced_mask);
    accumulator_limb_four = (accumulator_limb_four & use_original_mask) | (reduced_limb_four & use_reduced_mask);

    let mut authentication_tag_word_zero = ((accumulator_limb_zero | (accumulator_limb_one << 26)) & UINT32_MASK) + load_little_endian_u32(one_time_key, 16) as u64;
    let mut authentication_tag_word_one = (((accumulator_limb_one >> 6) | (accumulator_limb_two << 20)) & UINT32_MASK) + load_little_endian_u32(one_time_key, 20) as u64 + (authentication_tag_word_zero >> 32);
    authentication_tag_word_zero &= UINT32_MASK;
    let mut authentication_tag_word_two = (((accumulator_limb_two >> 12) | (accumulator_limb_three << 14)) & UINT32_MASK) + load_little_endian_u32(one_time_key, 24) as u64 + (authentication_tag_word_one >> 32);
    authentication_tag_word_one &= UINT32_MASK;
    let mut authentication_tag_word_three = (((accumulator_limb_three >> 18) | (accumulator_limb_four << 8)) & UINT32_MASK) + load_little_endian_u32(one_time_key, 28) as u64 + (authentication_tag_word_two >> 32);
    authentication_tag_word_two &= UINT32_MASK;
    authentication_tag_word_three &= UINT32_MASK;

    let mut tag = [0u8; TAG_SIZE];
    tag[0..4].copy_from_slice(&(authentication_tag_word_zero as u32).to_le_bytes());
    tag[4..8].copy_from_slice(&(authentication_tag_word_one as u32).to_le_bytes());
    tag[8..12].copy_from_slice(&(authentication_tag_word_two as u32).to_le_bytes());
    tag[12..16].copy_from_slice(&(authentication_tag_word_three as u32).to_le_bytes());
    Ok(tag)
}

fn build_authentication_data(associated_data: &[u8], ciphertext: &[u8]) -> Vec<u8> {
    let associated_padding = (16 - associated_data.len() % 16) % 16;
    let ciphertext_padding = (16 - ciphertext.len() % 16) % 16;
    let mut authentication_data = Vec::with_capacity(
        associated_data.len() + associated_padding + ciphertext.len() + ciphertext_padding + 16,
    );
    authentication_data.extend_from_slice(associated_data);
    authentication_data.resize(authentication_data.len() + associated_padding, 0);
    authentication_data.extend_from_slice(ciphertext);
    authentication_data.resize(authentication_data.len() + ciphertext_padding, 0);
    authentication_data.extend_from_slice(&(associated_data.len() as u64).to_le_bytes());
    authentication_data.extend_from_slice(&(ciphertext.len() as u64).to_le_bytes());
    authentication_data
}

fn chacha20_poly1305_encrypt(
    key: &[u8],
    nonce: &[u8],
    plaintext: &[u8],
    associated_data: &[u8],
) -> ApplicationResult<(Vec<u8>, [u8; TAG_SIZE])> {
    let first_block = chacha20_block(key, 0, nonce)?;
    let one_time_key = &first_block[..32];
    let ciphertext = chacha20_xor(key, nonce, 1, plaintext)?;
    let authentication_data = build_authentication_data(associated_data, &ciphertext);
    let authentication_tag = poly1305_mac(&authentication_data, one_time_key)?;
    Ok((ciphertext, authentication_tag))
}

fn chacha20_poly1305_decrypt(
    key: &[u8],
    nonce: &[u8],
    ciphertext: &[u8],
    authentication_tag: &[u8],
    associated_data: &[u8],
) -> ApplicationResult<Vec<u8>> {
    if authentication_tag.len() != TAG_SIZE {
        return Err("authentication tag must be 16 bytes".to_string());
    }
    let first_block = chacha20_block(key, 0, nonce)?;
    let one_time_key = &first_block[..32];
    let authentication_data = build_authentication_data(associated_data, ciphertext);
    let expected_tag = poly1305_mac(&authentication_data, one_time_key)?;
    let mut difference = 0u8;
    for index in 0..TAG_SIZE {
        difference |= expected_tag[index] ^ authentication_tag[index];
    }
    if difference != 0 {
        return Err("authentication failed".to_string());
    }
    chacha20_xor(key, nonce, 1, ciphertext)
}

#[cfg(windows)]
fn fill_random(buffer: &mut [u8]) -> io::Result<()> {
    if buffer.len() > u32::MAX as usize {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "random request is too large"));
    }
    let status = unsafe {
        bcrypt_generate_random(
            std::ptr::null_mut(),
            buffer.as_mut_ptr(),
            buffer.len() as u32,
            BCRYPT_USE_SYSTEM_PREFERRED_RNG,
        )
    };
    if status == 0 {
        Ok(())
    } else {
        Err(io::Error::other(format!("BCryptGenRandom failed: 0x{:08X}", status as u32)))
    }
}

#[cfg(unix)]
fn fill_random(buffer: &mut [u8]) -> io::Result<()> {
    let mut random_source = File::open("/dev/urandom")?;
    random_source.read_exact(buffer)
}

#[cfg(not(any(windows, unix)))]
fn fill_random(_buffer: &mut [u8]) -> io::Result<()> {
    Err(io::Error::new(io::ErrorKind::Unsupported, "secure OS randomness is unsupported on this platform"))
}

fn random_array<const LENGTH: usize>() -> ApplicationResult<[u8; LENGTH]> {
    let mut bytes = [0u8; LENGTH];
    fill_random(&mut bytes).map_err(|error| error.to_string())?;
    Ok(bytes)
}

fn random_hexadecimal(byte_count: usize) -> ApplicationResult<String> {
    let mut bytes = vec![0u8; byte_count];
    fill_random(&mut bytes).map_err(|error| error.to_string())?;
    let mut output = String::with_capacity(byte_count * 2);
    const HEXADECIMAL_DIGITS: &[u8; 16] = b"0123456789abcdef";
    for byte in bytes {
        output.push(HEXADECIMAL_DIGITS[(byte >> 4) as usize] as char);
        output.push(HEXADECIMAL_DIGITS[(byte & 0x0F) as usize] as char);
    }
    Ok(output)
}

#[cfg(windows)]
fn replace_file(source: &Path, destination: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    let source_wide: Vec<u16> = source.as_os_str().encode_wide().chain(std::iter::once(0)).collect();
    let destination_wide: Vec<u16> = destination.as_os_str().encode_wide().chain(std::iter::once(0)).collect();
    let result = unsafe { move_file_replace_existing_wide(source_wide.as_ptr(), destination_wide.as_ptr(), MOVEFILE_REPLACE_EXISTING) };
    if result != 0 {
        Ok(())
    } else {
        Err(io::Error::last_os_error())
    }
}

#[cfg(not(windows))]
fn replace_file(source: &Path, destination: &Path) -> io::Result<()> {
    fs::rename(source, destination)
}

fn temporary_path(file_path: &Path) -> ApplicationResult<PathBuf> {
    let mut temporary_name = file_path.as_os_str().to_os_string();
    temporary_name.push(".");
    temporary_name.push(random_hexadecimal(8)?);
    temporary_name.push(".tmp");
    Ok(PathBuf::from(temporary_name))
}

fn process_file(file_path: &Path, key: &[u8], mode: OperationMode) -> ApplicationResult<()> {
    let file_data = fs::read(file_path).map_err(|error| error.to_string())?;
    let output_data = match mode {
        OperationMode::Encrypt => {
            let nonce = random_array::<NONCE_SIZE>()?;
            let (ciphertext, authentication_tag) = chacha20_poly1305_encrypt(key, &nonce, &file_data, b"")?;
            let mut output = Vec::with_capacity(NONCE_SIZE + TAG_SIZE + ciphertext.len());
            output.extend_from_slice(&nonce);
            output.extend_from_slice(&authentication_tag);
            output.extend_from_slice(&ciphertext);
            output
        }
        OperationMode::Decrypt => {
            if file_data.len() < NONCE_SIZE + TAG_SIZE {
                return Err("encrypted file is too short".to_string());
            }
            let nonce = &file_data[..NONCE_SIZE];
            let authentication_tag = &file_data[NONCE_SIZE..NONCE_SIZE + TAG_SIZE];
            let ciphertext = &file_data[NONCE_SIZE + TAG_SIZE..];
            chacha20_poly1305_decrypt(key, nonce, ciphertext, authentication_tag, b"")?
        }
    };

    let temporary_file_path = temporary_path(file_path)?;
    let operation_result = (|| -> ApplicationResult<()> {
        let mut temporary_file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary_file_path)
            .map_err(|error| error.to_string())?;
        temporary_file.write_all(&output_data).map_err(|error| error.to_string())?;
        drop(temporary_file);
        replace_file(&temporary_file_path, file_path).map_err(|error| error.to_string())?;
        Ok(())
    })();

    if temporary_file_path.exists() {
        fs::remove_file(&temporary_file_path).map_err(|error| error.to_string())?;
    }
    operation_result
}

fn walk_directory(directory: &Path, key: &[u8], mode: OperationMode) {
    let entries = match fs::read_dir(directory) {
        Ok(entries) => entries,
        Err(_) => return,
    };
    let mut file_paths = Vec::new();
    let mut directory_paths = Vec::new();
    for entry_result in entries {
        let entry = match entry_result {
            Ok(entry) => entry,
            Err(_) => continue,
        };
        let path = entry.path();
        let is_directory = fs::metadata(&path).map(|metadata| metadata.is_dir()).unwrap_or(false);
        if is_directory {
            let is_symlink = entry.file_type().map(|file_type| file_type.is_symlink()).unwrap_or(false);
            if !is_symlink {
                directory_paths.push(path);
            }
        } else {
            file_paths.push(path);
        }
    }
    for file_path in file_paths {
        match process_file(&file_path, key, mode) {
            Ok(()) => println!("[OK] {}", file_path.display()),
            Err(error) => println!("[ERROR] {}: {}", file_path.display(), error),
        }
    }
    for child_directory in directory_paths {
        walk_directory(&child_directory, key, mode);
    }
}

fn process_path(path: &Path, key: &[u8], mode: OperationMode) -> ApplicationResult<()> {
    if path.is_file() {
        return process_file(path, key, mode);
    }
    if !path.is_dir() {
        return Err("path does not exist".to_string());
    }
    walk_directory(path, key, mode);
    Ok(())
}

fn hexadecimal_value(byte: u8) -> Option<u8> {
    match byte {
        b'0'..=b'9' => Some(byte - b'0'),
        b'a'..=b'f' => Some(byte - b'a' + 10),
        b'A'..=b'F' => Some(byte - b'A' + 10),
        _ => None,
    }
}

fn bytes_from_hexadecimal_like_python(input: &str) -> ApplicationResult<Vec<u8>> {
    let bytes = input.as_bytes();
    let mut output = Vec::with_capacity(bytes.len() / 2);
    let mut index = 0usize;
    while index < bytes.len() {
        while index < bytes.len() && bytes[index].is_ascii_whitespace() {
            index += 1;
        }
        if index == bytes.len() {
            break;
        }
        if index + 1 >= bytes.len() {
            return Err("Key must be hexadecimal".to_string());
        }
        let high = hexadecimal_value(bytes[index]).ok_or_else(|| "Key must be hexadecimal".to_string())?;
        let low = hexadecimal_value(bytes[index + 1]).ok_or_else(|| "Key must be hexadecimal".to_string())?;
        output.push((high << 4) | low);
        index += 2;
    }
    Ok(output)
}

fn input(prompt: &str) -> io::Result<String> {
    print!("{}", prompt);
    io::stdout().flush()?;
    let mut line = String::new();
    io::stdin().read_line(&mut line)?;
    Ok(line.trim().to_string())
}

fn main() {
    loop {
        println!("ChaCha20-Poly1305");
        println!("1. Encrypt");
        println!("2. Decrypt");
        let choice = match input("> ") {
            Ok(value) => value,
            Err(error) => {
                println!("[ERROR] {}", error);
                continue;
            }
        };
        let mode = match choice.as_str() {
            "1" => OperationMode::Encrypt,
            "2" => OperationMode::Decrypt,
            _ => {
                println!("Invalid mode");
                continue;
            }
        };
        let path_text = match input("File or directory: ") {
            Ok(value) => value.trim_matches('"').to_string(),
            Err(error) => {
                println!("[ERROR] {}", error);
                continue;
            }
        };
        let key_hexadecimal = match input("Key (64 hexadecimal characters): ") {
            Ok(value) => value,
            Err(error) => {
                println!("[ERROR] {}", error);
                continue;
            }
        };
        let key = match bytes_from_hexadecimal_like_python(&key_hexadecimal) {
            Ok(key) => key,
            Err(_) => {
                println!("Key must be hexadecimal");
                continue;
            }
        };
        if key.len() != KEY_SIZE {
            println!("Key must contain exactly 32 bytes");
            continue;
        }
        match process_path(Path::new(&path_text), &key, mode) {
            Ok(()) => println!("Done."),
            Err(error) => println!("[ERROR] {}", error),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn decode_hex(input: &str) -> Vec<u8> {
        bytes_from_hexadecimal_like_python(input).unwrap()
    }

    #[test]
    fn poly1305_reference_vector() {
        let key = decode_hex("85d6be7857556d337f4452fe42d506a80103808afb0db2fd4abff6af4149f51b");
        let tag = poly1305_mac(b"Cryptographic Forum Research Group", &key).unwrap();
        assert_eq!(tag.to_vec(), decode_hex("a8061dc1305136c6c22b8baf0c0127a9"));
    }

    #[test]
    fn python_interoperability_vector() {
        let key = decode_hex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f");
        let nonce = decode_hex("000102030405060708090a0b");
        let plaintext = b"Rust/Python interoperability test";
        let expected_ciphertext = decode_hex("db8e7b740647dc34dfec51d3f1737a06bb1fc2822315cfd08afe5bbc55b4c34f98");
        let expected_tag = decode_hex("077973212ff7ea408075de8e930cfb9f");
        let (ciphertext, tag) = chacha20_poly1305_encrypt(&key, &nonce, plaintext, b"").unwrap();
        assert_eq!(ciphertext, expected_ciphertext);
        assert_eq!(tag.to_vec(), expected_tag);
        let decrypted = chacha20_poly1305_decrypt(&key, &nonce, &ciphertext, &tag, b"").unwrap();
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn python_file_container_layout() {
        let key = decode_hex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f");
        let nonce = decode_hex("000102030405060708090a0b");
        let plaintext = b"Rust/Python interoperability test";
        let expected = decode_hex("000102030405060708090a0b077973212ff7ea408075de8e930cfb9fdb8e7b740647dc34dfec51d3f1737a06bb1fc2822315cfd08afe5bbc55b4c34f98");
        let (ciphertext, tag) = chacha20_poly1305_encrypt(&key, &nonce, plaintext, b"").unwrap();
        let mut container = Vec::new();
        container.extend_from_slice(&nonce);
        container.extend_from_slice(&tag);
        container.extend_from_slice(&ciphertext);
        assert_eq!(container, expected);
    }
}
