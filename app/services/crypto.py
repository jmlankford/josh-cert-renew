"""
Fernet-based symmetric encryption for all secrets stored in SQLite.

The Fernet key is derived deterministically from MASTER_SECRET using SHA-256
so that any printable string works as the environment variable value — the
user does not need to generate a base64-encoded key themselves.
"""

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

_fernet: Fernet | None = None


def _build_fernet() -> Fernet:
    secret = os.environ.get("MASTER_SECRET", "")
    if not secret:
        raise RuntimeError("MASTER_SECRET environment variable is not set — cannot initialise encryption")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = _build_fernet()
    return _fernet


def encrypt(plaintext: str) -> str:
    """Return Fernet-encrypted, base64-encoded ciphertext as a plain str."""
    return get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet ciphertext string. Raises ValueError on bad token."""
    try:
        return get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Decryption failed — token is invalid or MASTER_SECRET changed") from exc
