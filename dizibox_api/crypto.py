"""Crypto utilities for decrypting MolySTREAM & player payloads."""

import base64
import hashlib
from typing import Tuple
from Crypto.Cipher import AES

from dizibox_api.exceptions import DecryptionError


def evp_bytes_to_key(password: bytes, salt: bytes, key_len: int = 32, iv_len: int = 16) -> Tuple[bytes, bytes]:
    """OpenSSL EVP_BytesToKey equivalent for CryptoJS AES compatibility."""
    d = b""
    d_i = b""
    while len(d) < key_len + iv_len:
        d_i = hashlib.md5(d_i + password + salt).digest()
        d += d_i
    return d[:key_len], d[key_len:key_len + iv_len]


def decrypt_cryptojs_aes(ciphertext_b64: str, password: str) -> str:
    """Decrypt CryptoJS AES ciphertext formatted as 'Salted__<salt><ciphertext>'."""
    try:
        raw = base64.b64decode(ciphertext_b64)
        if len(raw) < 16 or raw[:8] != b"Salted__":
            raise DecryptionError("Invalid or missing Salted__ prefix in ciphertext")

        salt = raw[8:16]
        encrypted_data = raw[16:]
        key, iv = evp_bytes_to_key(password.encode("utf-8"), salt)

        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(encrypted_data)

        # Remove PKCS7 padding
        pad_len = decrypted[-1]
        if pad_len > 16:
            # Fallback if unpadded or malformed
            return decrypted.decode("utf-8", errors="ignore")

        return decrypted[:-pad_len].decode("utf-8", errors="ignore")
    except Exception as e:
        if isinstance(e, DecryptionError):
            raise
        raise DecryptionError(f"Failed to decrypt CryptoJS AES payload: {e}") from e
