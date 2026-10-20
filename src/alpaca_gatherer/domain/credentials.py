"""Alpaca credential value objects.

Plain values exist only in memory during a run; their ``repr`` never shows them.

>>> PlainCredentials("key-id", "secret")
PlainCredentials(api_key=***, api_secret=***)
"""

from dataclasses import dataclass
from datetime import datetime

__all__ = ["EncryptedCredentials", "PlainCredentials"]


@dataclass(frozen=True, slots=True)
class PlainCredentials:
    """Decrypted Alpaca key and secret."""

    api_key: str
    api_secret: str

    def __repr__(self) -> str:
        return "PlainCredentials(api_key=***, api_secret=***)"

    __str__ = __repr__


@dataclass(frozen=True, slots=True)
class EncryptedCredentials:
    """The stored form: two ciphertexts plus registration and update times."""

    api_key_enc: str
    api_secret_enc: str
    created_at: datetime
    updated_at: datetime
