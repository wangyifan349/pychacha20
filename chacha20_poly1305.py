"""
This script implements the IETF ChaCha20-Poly1305 AEAD construction defined in RFC 8439 entirely in Python and provides an interactive CLI for in-place encryption and decryption of a single file or all files in a directory recursively. The ChaCha20 and Poly1305 primitives are implemented directly in this file, while the Python standard library is used only for filesystem operations and random nonce generation. File names and directory structure are preserved. Each encrypted file uses an independently generated 96-bit nonce and is stored as nonce || authentication tag || ciphertext; the CLI file-processing path uses empty associated data (AAD).
"""
import os
UINT32_MASK = 0xFFFFFFFF
POLY1305_PRIME = (1 << 130) - 5
POLY1305_CLAMP_MASK = 0x0FFFFFFC0FFFFFFC0FFFFFFC0FFFFFFF
# ------------------------------------------------------------
def quarter_round(state, first, second, third, fourth):
    state[first] = (state[first] + state[second]) & UINT32_MASK
    state[fourth] ^= state[first]
    state[fourth] = ((state[fourth] << 16) | (state[fourth] >> 16)) & UINT32_MASK
    state[third] = (state[third] + state[fourth]) & UINT32_MASK
    state[second] ^= state[third]
    state[second] = ((state[second] << 12) | (state[second] >> 20)) & UINT32_MASK
    state[first] = (state[first] + state[second]) & UINT32_MASK
    state[fourth] ^= state[first]
    state[fourth] = ((state[fourth] << 8) | (state[fourth] >> 24)) & UINT32_MASK
    state[third] = (state[third] + state[fourth]) & UINT32_MASK
    state[second] ^= state[third]
    state[second] = ((state[second] << 7) | (state[second] >> 25)) & UINT32_MASK
# ------------------------------------------------------------
def chacha20_block(key, counter, nonce):
    if len(key) != 32 or len(nonce) != 12:
        raise ValueError("ChaCha20 requires a 32-byte key and 12-byte nonce")
    if not 0 <= counter <= UINT32_MASK:
        raise ValueError("counter must be a 32-bit unsigned integer")
    constants = b"expand 32-byte k"
    state = (
        [int.from_bytes(constants[offset:offset + 4], "little") for offset in range(0, 16, 4)]
        + [int.from_bytes(key[offset:offset + 4], "little") for offset in range(0, 32, 4)]
        + [counter]
        + [int.from_bytes(nonce[offset:offset + 4], "little") for offset in range(0, 12, 4)]
    )
    working_state = state.copy()
    for _ in range(10):  # 20 rounds: 10 column/diagonal double rounds
        quarter_round(working_state, 0, 4, 8, 12)
        quarter_round(working_state, 1, 5, 9, 13)
        quarter_round(working_state, 2, 6, 10, 14)
        quarter_round(working_state, 3, 7, 11, 15)
        quarter_round(working_state, 0, 5, 10, 15)
        quarter_round(working_state, 1, 6, 11, 12)
        quarter_round(working_state, 2, 7, 8, 13)
        quarter_round(working_state, 3, 4, 9, 14)
    return b"".join(((working_state[index] + state[index]) & UINT32_MASK).to_bytes(4, "little") for index in range(16))
# ------------------------------------------------------------
def chacha20_xor(key, nonce, counter, data):
    if len(key) != 32 or len(nonce) != 12:
        raise ValueError("ChaCha20 requires a 32-byte key and 12-byte nonce")
    if not 0 <= counter <= UINT32_MASK:
        raise ValueError("counter must be a 32-bit unsigned integer")
    block_count = (len(data) + 63) // 64
    if counter + block_count > (1 << 32):
        raise ValueError("ChaCha20 counter overflow")
    output = bytearray(len(data))
    for block_index in range(block_count):
        keystream = chacha20_block(key, counter + block_index, nonce)
        block_offset = block_index * 64
        block = data[block_offset:block_offset + 64]
        for byte_index, byte_value in enumerate(block):
            output[block_offset + byte_index] = byte_value ^ keystream[byte_index]
    return bytes(output)
# ------------------------------------------------------------
def poly1305_mac(message, one_time_key):
    if len(one_time_key) != 32:
        raise ValueError("Poly1305 requires a 32-byte one-time key")
    r = int.from_bytes(one_time_key[:16], "little") & POLY1305_CLAMP_MASK  # Clamp r as required by Poly1305
    s = int.from_bytes(one_time_key[16:], "little")
    accumulator = 0
    for offset in range(0, len(message), 16):
        block = message[offset:offset + 16]
        block_value = int.from_bytes(block + b"\x01", "little")
        accumulator = ((accumulator + block_value) * r) % POLY1305_PRIME
    authentication_tag = (accumulator + s) & ((1 << 128) - 1)
    return authentication_tag.to_bytes(16, "little")
# ------------------------------------------------------------
def chacha20_poly1305_encrypt(key, nonce, plaintext, associated_data=b""):
    one_time_key = chacha20_block(key, 0, nonce)[:32]  # Counter 0 derives the Poly1305 one-time key
    ciphertext = chacha20_xor(key, nonce, 1, plaintext)  # Payload encryption starts at counter 1
    associated_data_padding = b"\x00" * ((-len(associated_data)) % 16)
    ciphertext_padding = b"\x00" * ((-len(ciphertext)) % 16)
    authentication_data = (
        associated_data + associated_data_padding + ciphertext + ciphertext_padding
        + len(associated_data).to_bytes(8, "little") + len(ciphertext).to_bytes(8, "little")
    )  # AAD || pad16 || ciphertext || pad16 || len(AAD) || len(ciphertext)
    authentication_tag = poly1305_mac(authentication_data, one_time_key)
    return ciphertext, authentication_tag
# ------------------------------------------------------------
def chacha20_poly1305_decrypt(key, nonce, ciphertext, authentication_tag, associated_data=b""):
    if len(authentication_tag) != 16:
        raise ValueError("authentication tag must be 16 bytes")
    one_time_key = chacha20_block(key, 0, nonce)[:32]
    associated_data_padding = b"\x00" * ((-len(associated_data)) % 16)
    ciphertext_padding = b"\x00" * ((-len(ciphertext)) % 16)
    authentication_data = (
        associated_data + associated_data_padding + ciphertext + ciphertext_padding
        + len(associated_data).to_bytes(8, "little") + len(ciphertext).to_bytes(8, "little")
    )
    expected_tag = poly1305_mac(authentication_data, one_time_key)
    difference = 0  # Compare every tag byte before deciding whether authentication failed
    for expected_byte, received_byte in zip(expected_tag, authentication_tag):
        difference |= expected_byte ^ received_byte
    if difference != 0:
        raise ValueError("authentication failed")
    return chacha20_xor(key, nonce, 1, ciphertext)
# ------------------------------------------------------------
def process_file(file_path, key, mode):
    with open(file_path, "rb") as file:
        file_data = file.read()
    if mode == "encrypt":
        nonce = os.urandom(12)
        ciphertext, authentication_tag = chacha20_poly1305_encrypt(key, nonce, file_data)
        output_data = nonce + authentication_tag + ciphertext
    else:
        if len(file_data) < 28:
            raise ValueError("encrypted file is too short")
        nonce = file_data[:12]
        authentication_tag = file_data[12:28]
        ciphertext = file_data[28:]
        output_data = chacha20_poly1305_decrypt(key, nonce, ciphertext, authentication_tag)
    temporary_path = file_path + "." + os.urandom(8).hex() + ".tmp"
    try:
        with open(temporary_path, "xb") as file:  # Exclusive creation avoids overwriting an existing file
            file.write(output_data)
        os.replace(temporary_path, file_path)
    finally:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
# ------------------------------------------------------------
def process_path(path, key, mode):
    if os.path.isfile(path):
        process_file(path, key, mode)
        return
    if not os.path.isdir(path):
        raise ValueError("path does not exist")
    for current_directory, _, file_names in os.walk(path):
        for file_name in file_names:
            file_path = os.path.join(current_directory, file_name)
            try:
                process_file(file_path, key, mode)
                print(f"[OK] {file_path}")
            except Exception as error:
                print(f"[ERROR] {file_path}: {error}")
# ------------------------------------------------------------
if __name__ == "__main__":
    print("ChaCha20-Poly1305")
    print("1. Encrypt")
    print("2. Decrypt")
    choice = input("> ").strip()
    if choice == "1":
        mode = "encrypt"
    elif choice == "2":
        mode = "decrypt"
    else:
        raise ValueError("invalid mode")
    path = input("File or directory: ").strip().strip('"')
    key_hex = input("Key (64 hexadecimal characters): ").strip()
    try:
        key = bytes.fromhex(key_hex)
    except ValueError:
        raise ValueError("key must be hexadecimal")
    if len(key) != 32:
        raise ValueError("key must contain exactly 32 bytes")
    process_path(path, key, mode)
    print("Done.")
