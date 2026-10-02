"""Encrypt connector tokens before they are written to the database."""

from __future__ import annotations

import base64
import hashlib


def _fernet(key: str):
    from cryptography.fernet import Fernet

    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_token(secret: str, key: str) -> str:
    if not key:
        raise RuntimeError("Set TOKEN_KEY before storing a connector token.")
    return _fernet(key).encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_token(ciphertext: str, key: str) -> str:
    if not key:
        raise RuntimeError("Set TOKEN_KEY before reading a connector token.")
    return _fernet(key).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
