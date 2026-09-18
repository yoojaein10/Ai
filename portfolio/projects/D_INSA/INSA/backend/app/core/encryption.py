"""AES-256 encryption for sensitive fields (e.g. bank account numbers)."""

import base64
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

from app.core.config import settings


def _get_key() -> bytes:
    key = settings.AES_KEY
    if not key:
        raise ValueError("AES_KEY environment variable is not set")
    return base64.b64decode(key)


def encrypt(plaintext: str) -> str:
    key = _get_key()
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext.encode("utf-8")) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encrypted = cipher.encryptor().update(padded) + cipher.encryptor().finalize()
    return base64.b64encode(iv + encrypted).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    key = _get_key()
    raw = base64.b64decode(ciphertext)
    iv, encrypted = raw[:16], raw[16:]
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    padded = cipher.decryptor().update(encrypted) + cipher.decryptor().finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")


def mask_account(account_number: str) -> str:
    if len(account_number) < 4:
        return "****"
    return "*" * (len(account_number) - 4) + account_number[-4:]
