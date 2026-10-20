"""Fernet implementation of ``SecretCipher`` (research R8).

>>> from cryptography.fernet import Fernet
>>> cipher = FernetCipher(Fernet.generate_key().decode())
>>> cipher.decrypt(cipher.encrypt("value"))
'value'
"""

from cryptography.fernet import Fernet, InvalidToken

from alpaca_gatherer.domain.errors import CredentialsUndecryptable

__all__ = ["FernetCipher"]


class FernetCipher:
    """Authenticated symmetric encryption with the configured ``FIELD_ENCRYPTION_KEY``."""

    def __init__(self, key: str) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plain: str) -> str:
        """Return the Fernet token of ``plain``."""
        return self._fernet.encrypt(plain.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Return the plain text; a wrong key or a damaged token raises
        ``CredentialsUndecryptable``."""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken, ValueError:
            raise CredentialsUndecryptable() from None
