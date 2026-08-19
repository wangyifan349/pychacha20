#!/usr/bin/env python3

"""
Bitcoin secp256k1 private-key utility.

Calculation flow:

    secure random integer
    -> secp256k1 private key
    -> decimal / 32-byte HEX / WIF
    -> public point Q = private_key * G
    -> compressed public key
    -> SHA256
    -> RIPEMD160
    -> HASH160
    -> SegWit v0 witness program
    -> Bech32
    -> bc1q... P2WPKH address

The secp256k1 point arithmetic and Bech32 calculation are implemented
directly so the mathematical process stays visible. The external
"base58" package is used only for WIF Base58Check encoding/decoding.
"""

import hashlib
import secrets
import base58

FIELD_PRIME = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
CURVE_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GENERATOR_X = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GENERATOR_Y = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8
GENERATOR_POINT = (GENERATOR_X, GENERATOR_Y)
BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"

# secp256k1:
#
#     y^2 = x^3 + 7 (mod FIELD_PRIME)
#
# A valid private key k satisfies:
#
#     1 <= k < CURVE_ORDER
#
# The public key is the elliptic-curve point:
#
#     Q = k * GENERATOR_POINT


def sha256(data):
    return hashlib.sha256(data).digest()


def ripemd160(data):
    try:
        hash_object = hashlib.new("ripemd160")
    except ValueError:
        raise RuntimeError("RIPEMD160 is not supported by this Python/OpenSSL build.")
    hash_object.update(data)
    return hash_object.digest()


def hash160(data):
    # Bitcoin HASH160:
    #
    #     RIPEMD160(SHA256(data))
    #
    # For P2WPKH, data is the compressed public key.
    sha256_hash = sha256(data)
    return ripemd160(sha256_hash)


def modular_inverse(value):
    # Division in a finite field is multiplication by a modular inverse:
    #
    #     a / b mod P = a * b^(-1) mod P
    return pow(value, -1, FIELD_PRIME)


def is_point_on_curve(point):
    if point is None:
        return True

    x_coordinate, y_coordinate = point

    if x_coordinate < 0 or x_coordinate >= FIELD_PRIME:
        return False

    if y_coordinate < 0 or y_coordinate >= FIELD_PRIME:
        return False

    left_side = y_coordinate * y_coordinate % FIELD_PRIME
    right_side = (x_coordinate * x_coordinate * x_coordinate + 7) % FIELD_PRIME
    return left_side == right_side


def add_points(first_point, second_point):
    # Elliptic-curve point addition.
    #
    # Different points:
    #
    #     slope = (y2 - y1) / (x2 - x1) mod P
    #
    # Point doubling:
    #
    #     slope = (3*x1^2) / (2*y1) mod P
    #
    # Result:
    #
    #     x3 = slope^2 - x1 - x2 mod P
    #     y3 = slope*(x1 - x3) - y1 mod P

    if first_point is None:
        return second_point

    if second_point is None:
        return first_point

    if not is_point_on_curve(first_point):
        raise ValueError("First point is not on secp256k1.")

    if not is_point_on_curve(second_point):
        raise ValueError("Second point is not on secp256k1.")

    first_x, first_y = first_point
    second_x, second_y = second_point

    same_x = first_x == second_x
    opposite_y = (first_y + second_y) % FIELD_PRIME == 0

    if same_x and opposite_y:
        return None

    if first_point == second_point:
        if first_y == 0:
            return None

        numerator = 3 * first_x * first_x
        denominator = 2 * first_y
    else:
        numerator = second_y - first_y
        denominator = second_x - first_x

    numerator %= FIELD_PRIME
    denominator %= FIELD_PRIME

    denominator_inverse = modular_inverse(denominator)
    slope = numerator * denominator_inverse % FIELD_PRIME

    result_x = slope * slope - first_x - second_x
    result_x %= FIELD_PRIME

    result_y = slope * (first_x - result_x) - first_y
    result_y %= FIELD_PRIME

    result_point = (result_x, result_y)

    if not is_point_on_curve(result_point):
        raise RuntimeError("Point calculation failed.")

    return result_point


def multiply_point(scalar, point=GENERATOR_POINT):
    # Double-and-Add computes scalar * point efficiently.
    #
    # Example:
    #
    #     13 = 1101 binary
    #     13G = 8G + 4G + G
    #
    # current_point progresses:
    #
    #     G -> 2G -> 4G -> 8G -> ...

    if scalar < 1 or scalar >= CURVE_ORDER:
        raise ValueError("Scalar is outside the secp256k1 range.")

    if not is_point_on_curve(point):
        raise ValueError("Point is not on secp256k1.")

    result_point = None
    current_point = point
    current_scalar = scalar

    while current_scalar > 0:
        if current_scalar & 1:
            result_point = add_points(result_point, current_point)

        current_point = add_points(current_point, current_point)
        current_scalar >>= 1

    return result_point


def validate_private_key(private_key):
    if private_key < 1:
        raise ValueError("Private key cannot be zero.")

    if private_key >= CURVE_ORDER:
        raise ValueError("Private key is outside the secp256k1 range.")


def generate_private_key():
    # secrets.randbelow() uses a cryptographically secure random source.
    # randbelow(CURVE_ORDER - 1) gives 0..N-2, then +1 gives 1..N-1.
    random_value = secrets.randbelow(CURVE_ORDER - 1)
    return random_value + 1


def private_key_to_hex(private_key):
    # A secp256k1 private key is serialized as exactly 32 bytes,
    # which becomes 64 hexadecimal characters.
    validate_private_key(private_key)
    private_bytes = private_key.to_bytes(32, "big")
    return private_bytes.hex()


def private_key_to_wif(private_key, compressed=True):
    # Bitcoin mainnet WIF payload:
    #
    #     0x80 || 32-byte private key
    #
    # For compressed public keys:
    #
    #     0x80 || private key || 0x01
    #
    # base58.b58encode_check() performs:
    #
    #     checksum = SHA256(SHA256(payload))[:4]
    #     Base58(payload || checksum)

    validate_private_key(private_key)

    private_bytes = private_key.to_bytes(32, "big")
    payload = b"\x80" + private_bytes

    if compressed:
        payload += b"\x01"

    encoded_wif = base58.b58encode_check(payload)
    return encoded_wif.decode("ascii")


def normalize_private_key_text(private_key_text):
    normalized_text = private_key_text.strip()

    if normalized_text.startswith("0x") or normalized_text.startswith("0X"):
        normalized_text = normalized_text[2:]

    return normalized_text


def is_hexadecimal_private_key(private_key_text):
    normalized_text = normalize_private_key_text(private_key_text)

    if len(normalized_text) != 64:
        return False

    hexadecimal_characters = "0123456789abcdefABCDEF"

    for character in normalized_text:
        if character not in hexadecimal_characters:
            return False

    return True


def is_decimal_private_key(private_key_text):
    normalized_text = private_key_text.strip()

    if not normalized_text:
        return False

    if len(normalized_text) == 64:
        return False

    for character in normalized_text:
        if character < "0" or character > "9":
            return False

    return True


def decode_wif(private_key_text):
    try:
        payload = base58.b58decode_check(private_key_text.strip())
    except Exception:
        return None

    return payload


def is_ambiguous_numeric_private_key(private_key_text):
    # A string containing exactly 64 decimal digits is ambiguous:
    #
    #     1234... could mean a decimal integer
    #     1234... could also mean a 32-byte hexadecimal value
    #
    # Guessing here could silently import the wrong private key, so the
    # program rejects this rare ambiguous form instead. Prefix hexadecimal
    # input with "0x", or import the key as WIF, to make the format explicit.
    normalized_text = private_key_text.strip()

    if len(normalized_text) != 64:
        return False

    for character in normalized_text:
        if character < "0" or character > "9":
            return False

    return True


def detect_private_key_format(private_key_text):
    # Automatic import recognition:
    #
    #     64-character HEX / 0x-prefixed HEX
    #     decimal integer
    #     mainnet compressed WIF
    #     mainnet uncompressed WIF
    #
    # A digits-only 64-character value is rejected as ambiguous instead
    # of guessing and potentially importing a different private key.
    stripped_text = private_key_text.strip()

    if stripped_text.startswith("0x") or stripped_text.startswith("0X"):
        if is_hexadecimal_private_key(private_key_text):
            return "HEX"
        return "UNKNOWN"

    if is_ambiguous_numeric_private_key(private_key_text):
        return "AMBIGUOUS_NUMERIC_64"

    if is_hexadecimal_private_key(private_key_text):
        return "HEX"

    if is_decimal_private_key(private_key_text):
        return "DECIMAL"

    payload = decode_wif(private_key_text)

    if payload is None:
        return "UNKNOWN"

    if len(payload) == 34:
        network_prefix = payload[0]
        compression_flag = payload[33]

        if network_prefix == 0x80 and compression_flag == 0x01:
            return "WIF_COMPRESSED"

    if len(payload) == 33:
        network_prefix = payload[0]

        if network_prefix == 0x80:
            return "WIF_UNCOMPRESSED"

    return "UNKNOWN"


def import_hex_private_key(private_key_text):
    normalized_text = normalize_private_key_text(private_key_text)
    private_key = int(normalized_text, 16)
    validate_private_key(private_key)
    return private_key


def import_decimal_private_key(private_key_text):
    private_key = int(private_key_text.strip(), 10)
    validate_private_key(private_key)
    return private_key


def import_wif_private_key(private_key_text):
    payload = decode_wif(private_key_text)

    if payload is None:
        raise ValueError("Invalid WIF checksum or Base58 encoding.")

    private_bytes = payload[1:33]
    private_key = int.from_bytes(private_bytes, "big")
    validate_private_key(private_key)
    return private_key


def import_private_key(private_key_text):
    key_format = detect_private_key_format(private_key_text)

    if key_format == "HEX":
        private_key = import_hex_private_key(private_key_text)
        return private_key, key_format

    if key_format == "DECIMAL":
        private_key = import_decimal_private_key(private_key_text)
        return private_key, key_format

    if key_format == "WIF_COMPRESSED":
        private_key = import_wif_private_key(private_key_text)
        return private_key, key_format

    if key_format == "WIF_UNCOMPRESSED":
        private_key = import_wif_private_key(private_key_text)
        return private_key, key_format

    if key_format == "AMBIGUOUS_NUMERIC_64":
        raise ValueError(
            "A 64-digit numeric key is ambiguous between decimal and HEX. "
            "Use 0x before HEX, or import the key as WIF."
        )

    raise ValueError("Private key format is not recognized. Use decimal integer, 32-byte HEX, or Bitcoin mainnet WIF.")


def private_key_to_public_point(private_key):
    # Public-key derivation:
    #
    #     Q = private_key * G
    #
    # This is elliptic-curve scalar multiplication, not hashing.
    validate_private_key(private_key)
    return multiply_point(private_key, GENERATOR_POINT)


def public_key_to_uncompressed(point):
    # Uncompressed SEC public key:
    #
    #     0x04 || X || Y
    #
    # Total length: 65 bytes.

    if point is None or not is_point_on_curve(point):
        raise ValueError("Invalid public point.")

    x_coordinate, y_coordinate = point
    x_bytes = x_coordinate.to_bytes(32, "big")
    y_bytes = y_coordinate.to_bytes(32, "big")
    return b"\x04" + x_bytes + y_bytes


def public_key_to_compressed(point):
    # Compressed SEC public key:
    #
    #     even Y -> 0x02 || X
    #     odd Y  -> 0x03 || X
    #
    # Total length: 33 bytes.

    if point is None or not is_point_on_curve(point):
        raise ValueError("Invalid public point.")

    x_coordinate, y_coordinate = point

    if y_coordinate % 2 == 0:
        prefix = b"\x02"
    else:
        prefix = b"\x03"

    x_bytes = x_coordinate.to_bytes(32, "big")
    return prefix + x_bytes


def bech32_polymod(values):
    # BIP173 Bech32 checksum polynomial.
    generators = (
        0x3B6A57B2,
        0x26508E6D,
        0x1EA119FA,
        0x3D4233DD,
        0x2A1462B3
    )

    checksum = 1

    for value in values:
        top_bits = checksum >> 25
        checksum = ((checksum & 0x1FFFFFF) << 5) ^ value

        generator_index = 0

        while generator_index < 5:
            current_bit = (top_bits >> generator_index) & 1

            if current_bit:
                checksum ^= generators[generator_index]

            generator_index += 1

    return checksum


def expand_bech32_hrp(hrp):
    expanded_values = []

    for character in hrp:
        character_value = ord(character)
        high_bits = character_value >> 5
        expanded_values.append(high_bits)

    expanded_values.append(0)

    for character in hrp:
        character_value = ord(character)
        low_bits = character_value & 31
        expanded_values.append(low_bits)

    return expanded_values


def create_bech32_checksum(hrp, data):
    values = expand_bech32_hrp(hrp)

    for value in data:
        values.append(value)

    values.extend((0, 0, 0, 0, 0, 0))

    checksum_value = bech32_polymod(values)
    checksum_value ^= 1

    checksum = []
    position = 0

    while position < 6:
        shift = 5 * (5 - position)
        checksum_part = checksum_value >> shift
        checksum_part &= 31
        checksum.append(checksum_part)
        position += 1

    return checksum


def encode_bech32(hrp, data):
    checksum = create_bech32_checksum(hrp, data)
    combined_values = []

    for value in data:
        combined_values.append(value)

    for value in checksum:
        combined_values.append(value)

    encoded_data = ""

    for value in combined_values:
        encoded_data += BECH32_CHARSET[value]

    return hrp + "1" + encoded_data


def convert_bits(data, source_bits, target_bits, pad=True):
    # Bech32 uses a 32-character alphabet, so each symbol represents
    # 5 bits. The 20-byte witness program is therefore regrouped
    # from 8-bit bytes into 5-bit values.
    accumulator = 0
    bit_count = 0
    result = []

    maximum_value = (1 << target_bits) - 1
    maximum_accumulator = (1 << (source_bits + target_bits - 1)) - 1

    for value in data:
        if value < 0:
            raise ValueError("Invalid bit-conversion value.")

        if value >> source_bits:
            raise ValueError("Input value is too large.")

        accumulator <<= source_bits
        accumulator |= value
        accumulator &= maximum_accumulator
        bit_count += source_bits

        while bit_count >= target_bits:
            bit_count -= target_bits
            converted_value = accumulator >> bit_count
            converted_value &= maximum_value
            result.append(converted_value)

    if pad and bit_count > 0:
        converted_value = accumulator << (target_bits - bit_count)
        converted_value &= maximum_value
        result.append(converted_value)

    if not pad and bit_count >= source_bits:
        raise ValueError("Invalid bit-conversion padding.")

    if not pad and bit_count > 0:
        remaining_value = accumulator << (target_bits - bit_count)
        remaining_value &= maximum_value

        if remaining_value != 0:
            raise ValueError("Non-zero bit-conversion padding.")

    return result


def public_key_to_witness_program(compressed_public_key):
    # P2WPKH witness program:
    #
    #     HASH160(compressed public key)
    #
    # Result length: 20 bytes.
    if len(compressed_public_key) != 33:
        raise ValueError("Compressed public key must be 33 bytes.")

    prefix = compressed_public_key[0]

    if prefix != 0x02 and prefix != 0x03:
        raise ValueError("Invalid compressed public key.")

    return hash160(compressed_public_key)


def public_key_to_script_pubkey(compressed_public_key):
    # Native SegWit v0 P2WPKH scriptPubKey:
    #
    #     00 14 <20-byte HASH160>
    #
    # 00 = witness version 0
    # 14 = hexadecimal 20, the witness-program length.
    witness_program = public_key_to_witness_program(compressed_public_key)
    return b"\x00\x14" + witness_program


def public_key_to_p2wpkh_address(compressed_public_key):
    # Address calculation:
    #
    #     compressed public key
    #     -> SHA256
    #     -> RIPEMD160
    #     -> 20-byte HASH160 witness program
    #     -> 8-bit to 5-bit conversion
    #     -> witness version 0
    #     -> Bech32 with mainnet HRP "bc"
    #     -> bc1q...
    witness_program = public_key_to_witness_program(compressed_public_key)
    converted_program = convert_bits(witness_program, 8, 5, True)

    address_data = [0]

    for value in converted_program:
        address_data.append(value)

    return encode_bech32("bc", address_data)


def run_self_test():
    private_key = 1
    public_point = private_key_to_public_point(private_key)
    compressed_public_key = public_key_to_compressed(public_point)

    expected_public_key = "0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"

    if compressed_public_key.hex() != expected_public_key:
        raise RuntimeError("secp256k1 self-test failed.")

    expected_hash160 = "751e76e8199196d454941c45d1b3a323f1433bd6"
    actual_hash160 = hash160(compressed_public_key).hex()

    if actual_hash160 != expected_hash160:
        raise RuntimeError("HASH160 self-test failed.")

    expected_address = "bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4"
    actual_address = public_key_to_p2wpkh_address(compressed_public_key)

    if actual_address != expected_address:
        raise RuntimeError("Bech32 self-test failed.")

    compressed_wif = private_key_to_wif(private_key, True)
    imported_private_key, imported_format = import_private_key(compressed_wif)

    if imported_private_key != private_key or imported_format != "WIF_COMPRESSED":
        raise RuntimeError("Compressed WIF import self-test failed.")

    uncompressed_wif = private_key_to_wif(private_key, False)
    imported_private_key, imported_format = import_private_key(uncompressed_wif)

    if imported_private_key != private_key or imported_format != "WIF_UNCOMPRESSED":
        raise RuntimeError("Uncompressed WIF import self-test failed.")

    private_key_hex = private_key_to_hex(private_key)
    explicit_hex = "0x" + private_key_hex
    imported_private_key, imported_format = import_private_key(explicit_hex)

    if imported_private_key != private_key or imported_format != "HEX":
        raise RuntimeError("HEX import self-test failed.")

    decimal_private_key = str(private_key)
    imported_private_key, imported_format = import_private_key(decimal_private_key)

    if imported_private_key != private_key or imported_format != "DECIMAL":
        raise RuntimeError("Decimal import self-test failed.")


def display_wallet(private_key, key_source, wallet_number=None):
    private_key_hex = private_key_to_hex(private_key)
    compressed_wif = private_key_to_wif(private_key, True)

    public_point = private_key_to_public_point(private_key)
    public_x, public_y = public_point

    uncompressed_public_key = public_key_to_uncompressed(public_point)
    compressed_public_key = public_key_to_compressed(public_point)

    witness_program = public_key_to_witness_program(compressed_public_key)
    script_pubkey = public_key_to_script_pubkey(compressed_public_key)
    receiving_address = public_key_to_p2wpkh_address(compressed_public_key)

    print()

    if wallet_number is None:
        print("=== Bitcoin secp256k1 Key ===")
    else:
        print("=== Bitcoin secp256k1 Key", wallet_number, "===")

    print("Source              :", key_source)
    print("Private Key Integer :", private_key)
    print("Private Key HEX     :", private_key_hex)
    print("Private Key WIF     :", compressed_wif)
    print("Public Key X        :", format(public_x, "064x"))
    print("Public Key Y        :", format(public_y, "064x"))
    print("Uncompressed Public :", uncompressed_public_key.hex())
    print("Compressed Public   :", compressed_public_key.hex())
    print("HASH160             :", witness_program.hex())
    print("P2WPKH scriptPubKey :", script_pubkey.hex())
    print("P2WPKH Address      :", receiving_address)


def generate_wallets(count=50):
    wallet_number = 1

    while wallet_number <= count:
        private_key = generate_private_key()
        display_wallet(private_key, "GENERATED", wallet_number)
        wallet_number += 1


def import_one_wallet():
    private_key_text = input("Enter private key (integer, HEX or WIF): ").strip()
    private_key, key_format = import_private_key(private_key_text)
    display_wallet(private_key, key_format)


def main():
    run_self_test()
    print("Self-test passed.")

    while True:
        print()
        print("1. Generate 50 private keys")
        print("2. Import one private key")
        selection = input("Select: ").strip()

        try:
            if selection == "1":
                generate_wallets(50)
            elif selection == "2":
                import_one_wallet()
            else:
                print("Error: Invalid selection.")
        except ValueError as error:
            print("Error:", error)


if __name__ == "__main__":
    main()
