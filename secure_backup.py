"""
Directory Backup Encryption Tool

This program compresses a directory into a high-compression 7z archive,
then encrypts the archive using ChaCha20-Poly1305 authenticated encryption.
During restoration, it decrypts the archive and extracts the original directory.

Dependencies:
pip install py7zr cryptography
"""

import os
import stat
import tempfile
import py7zr
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

SOURCE_DIRECTORY = "source"
OUTPUT_DIRECTORY = "output"
KEY_DIRECTORY = "keys"

ARCHIVE_PATH = os.path.join(OUTPUT_DIRECTORY, "backup.7z")
ENCRYPTED_ARCHIVE_PATH = os.path.join(OUTPUT_DIRECTORY, "backup.7z.enc")
KEY_PATH = os.path.join(KEY_DIRECTORY, "chacha20.key")

def atomic_write(file_path, data):
    directory_path = os.path.dirname(file_path) or "."
    file_descriptor, temporary_path = tempfile.mkstemp(dir=directory_path)
    try:
        with os.fdopen(file_descriptor, "wb") as output_file:
            output_file.write(data)
            output_file.flush()
            os.fsync(output_file.fileno())
        os.replace(temporary_path, file_path)
    except Exception:
        if os.path.exists(temporary_path):
            os.remove(temporary_path)
        raise

def create_key():
    os.makedirs(KEY_DIRECTORY, exist_ok=True)
    encryption_key = ChaCha20Poly1305.generate_key()
    atomic_write(KEY_PATH, encryption_key)
    try:
        os.chmod(KEY_PATH, 0o400)
    except Exception:
        os.chmod(KEY_PATH, stat.S_IREAD)
    print("Key file created:", KEY_PATH)
    print("Keep this key file safe. Lost key means lost encrypted data.")
    return encryption_key

def load_key():
    if not os.path.exists(KEY_PATH):
        raise FileNotFoundError("Key file not found")
    with open(KEY_PATH, "rb") as key_file:
        encryption_key = key_file.read()
    if len(encryption_key) != 32:
        raise ValueError("Invalid key length")
    print("Using key:", KEY_PATH)
    return encryption_key

def compress_directory():
    os.makedirs(OUTPUT_DIRECTORY, exist_ok=True)
    if os.path.exists(ARCHIVE_PATH):
        os.remove(ARCHIVE_PATH)
    with py7zr.SevenZipFile(
        ARCHIVE_PATH,
        "w",
        filters=[{"id": py7zr.FILTER_LZMA2, "preset": 9}]
    ) as archive_file:
        archive_file.writeall(
            SOURCE_DIRECTORY,
            arcname=os.path.basename(SOURCE_DIRECTORY)
        )
    print("Compression completed:", ARCHIVE_PATH)

def encrypt_file(input_path, output_path):
    encryption_key = load_key()
    cipher = ChaCha20Poly1305(encryption_key)
    with open(input_path, "rb") as input_file:
        plain_data = input_file.read()
    nonce = os.urandom(12)
    encrypted_data = cipher.encrypt(nonce, plain_data, None)
    atomic_write(output_path, nonce + encrypted_data)
    print("Encryption completed:", output_path)

def decrypt_file(input_path, output_path):
    encryption_key = load_key()
    cipher = ChaCha20Poly1305(encryption_key)
    with open(input_path, "rb") as encrypted_file:
        encrypted_data = encrypted_file.read()
    if len(encrypted_data) < 28:
        raise ValueError("Invalid encrypted file")
    nonce = encrypted_data[:12]
    cipher_data = encrypted_data[12:]
    plain_data = cipher.decrypt(nonce, cipher_data, None)
    atomic_write(output_path, plain_data)
    print("Decryption completed:", output_path)

def extract_directory():
    restore_directory = "restore"
    os.makedirs(restore_directory, exist_ok=True)
    with py7zr.SevenZipFile(ARCHIVE_PATH, "r") as archive_file:
        archive_file.extractall(path=restore_directory)
    print("Extraction completed:", restore_directory)

def create_backup():
    if not os.path.exists(KEY_PATH):
        create_key()
    compress_directory()
    encrypt_file(ARCHIVE_PATH, ENCRYPTED_ARCHIVE_PATH)
    os.remove(ARCHIVE_PATH)
    print("Backup completed:", ENCRYPTED_ARCHIVE_PATH)

def restore_backup():
    decrypt_file(ENCRYPTED_ARCHIVE_PATH, ARCHIVE_PATH)
    extract_directory()
    os.remove(ARCHIVE_PATH)
    print("Restore completed")

if __name__ == "__main__":
    operation_mode = input("Enter mode backup/restore: ").strip().lower()
    if operation_mode == "backup":
        create_backup()
    elif operation_mode == "restore":
        restore_backup()
    else:
        print("Invalid mode")
