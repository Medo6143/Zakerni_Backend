"""Fernet-based symmetric encryption helper.

Used to store Moodle LMS tokens at rest. The key comes from the
``FERNET_KEY`` environment variable (see .env.example) and must never be
committed or logged. Generate one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet
from django.conf import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.FERNET_KEY
    if not key:
        raise RuntimeError("FERNET_KEY is not set. Generate one and add it to your .env file.")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
