# 🔐 ChaCha20-Poly1305

A compact, pure-Python implementation of **ChaCha20-Poly1305 AEAD** based on **RFC 8439**, with an interactive CLI for encrypting or decrypting a single file or an entire directory.

The script uses only Python's standard library. It keeps file names and directory structure unchanged and generates a fresh 96-bit nonce for every encrypted file.

## ✨ Features

- 🔑 ChaCha20 with a 256-bit key
- 🛡️ Poly1305 authentication
- 🔐 ChaCha20-Poly1305 AEAD construction
- 📁 Single-file and recursive directory processing
- 🖥️ Interactive CLI
- 📦 No third-party dependencies
- 📝 No added file extension or magic/version marker
- 🎲 Independent random nonce for each encrypted file
- ✅ Authentication is checked before plaintext is returned

## 📦 Deployment

```bash
git clone https://github.com/wangyifan349/pychacha20
cd pychacha20
python chacha20ploy1305.py
```

## 🚀 Usage

Run:

```bash
python "chacha20_poly1305(1).py"
```

Choose the operation:

```text
ChaCha20-Poly1305
1. Encrypt
2. Decrypt
>
```

Then provide a file or directory and a 256-bit key encoded as **64 hexadecimal characters**:

```text
File or directory: ./data
Key (64 hexadecimal characters): 000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
```

The same key is required for decryption.

A random 256-bit key can be generated with Python:

```bash
python -c "import os; print(os.urandom(32).hex())"
```

> ⚠️ Keep the key safe. If the key is lost, the encrypted data cannot be recovered.

## 📄 Encrypted File Layout

The CLI stores each encrypted file as:

```text
nonce || authentication_tag || ciphertext
```

| Field | Size |
|---|---:|
| Nonce | 12 bytes |
| Authentication tag | 16 bytes |
| Ciphertext | Remaining bytes |

There is no magic value, version field, or identifying file extension. The 28-byte prefix contains only the nonce and authentication tag required for decryption.

## ⚙️ Algorithm Flow

### Encryption

1. Generate a random **96-bit nonce**.
2. Run the ChaCha20 block function with counter `0`.
3. Use the first 32 bytes of that block as the Poly1305 one-time key.
4. Encrypt the plaintext with ChaCha20 starting at counter `1`.
5. Construct the RFC 8439 authentication input:
   `AAD || pad16(AAD) || ciphertext || pad16(ciphertext) || len(AAD) || len(ciphertext)`.
6. Compute the 16-byte Poly1305 authentication tag.
7. Store `nonce || authentication_tag || ciphertext`.

### Decryption

1. Read the nonce, authentication tag, and ciphertext.
2. Regenerate the Poly1305 one-time key using ChaCha20 counter `0`.
3. Recompute and compare the authentication tag.
4. Reject the data if authentication fails.
5. Decrypt the ciphertext with ChaCha20 starting at counter `1`.

## 📌 Parameters

| Parameter | Value |
|---|---:|
| Key | 32 bytes / 256 bits |
| Nonce | 12 bytes / 96 bits |
| ChaCha20 block | 64 bytes |
| ChaCha20 rounds | 20 |
| Counter | 32-bit |
| Poly1305 tag | 16 bytes / 128 bits |

## ⚠️ Implementation Notes

- The cryptographic core supports `associated_data`, but the current file/CLI path does not supply AAD, so file processing uses an empty AAD value.
- Each file is read completely into memory before encryption or decryption.
- Directory processing is recursive and operates on files in place.
- Before replacing a file, the current implementation writes to `original_filename.tmp`. A pre-existing file with that exact temporary name may be overwritten, so avoid such name collisions.
- Pure Python is useful for learning, interoperability testing, and studying the construction, but it does **not** provide the constant-time guarantees or hardening expected from production cryptographic libraries.
- A nonce must never be reused with the same key. The CLI avoids manual nonce reuse by generating a new 12-byte nonce with `os.urandom(12)` for each encryption operation.

## 📚 Standards & References

The cryptographic construction is based on the official RFC Editor publication:

- 📘 [RFC 8439 — ChaCha20 and Poly1305 for IETF Protocols](https://www.rfc-editor.org/rfc/rfc8439.html)
- ℹ️ [RFC 8439 — RFC Editor Information](https://www.rfc-editor.org/info/rfc8439)
- 🛠️ [RFC 8439 — Errata](https://www.rfc-editor.org/errata/rfc8439)

RFC 8439 defines ChaCha20, Poly1305, and their AEAD combination, and obsoletes RFC 7539.
