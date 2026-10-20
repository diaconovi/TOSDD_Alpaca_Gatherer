"""Register, update and (inside a run) decrypt the Alpaca credentials.

Plain values are never stored, returned or logged: they are encrypted on the way in and decrypted
only on demand, at which point both values are registered with the log redaction filter.
"""

from alpaca_gatherer.application.ports import Clock, CredentialRepository, SecretCipher
from alpaca_gatherer.domain.credentials import EncryptedCredentials, PlainCredentials
from alpaca_gatherer.logging_setup import register_secret

__all__ = ["CredentialsProvider", "RegisterCredentials", "UpdateCredentials"]


class RegisterCredentials:
    """Store the credentials once; raises ``CredentialsExist`` if some are stored."""

    def __init__(self, repo: CredentialRepository, cipher: SecretCipher, clock: Clock) -> None:
        self._repo = repo
        self._cipher = cipher
        self._clock = clock

    async def __call__(self, api_key: str, api_secret: str) -> None:
        """Encrypt and store a key and secret."""
        now = self._clock.now()
        await self._repo.insert(
            EncryptedCredentials(
                api_key_enc=self._cipher.encrypt(api_key),
                api_secret_enc=self._cipher.encrypt(api_secret),
                created_at=now,
                updated_at=now,
            )
        )


class UpdateCredentials:
    """Replace stored credentials without decrypting the old ones (works after a key change)."""

    def __init__(self, repo: CredentialRepository, cipher: SecretCipher, clock: Clock) -> None:
        self._repo = repo
        self._cipher = cipher
        self._clock = clock

    async def __call__(self, api_key: str, api_secret: str) -> None:
        """Encrypt and replace; raises ``CredentialsNotFound`` if none are registered."""
        await self._repo.update(
            self._cipher.encrypt(api_key), self._cipher.encrypt(api_secret), self._clock.now()
        )


class CredentialsProvider:
    """Read access to the credentials for runs."""

    def __init__(self, repo: CredentialRepository, cipher: SecretCipher) -> None:
        self._repo = repo
        self._cipher = cipher

    async def exists(self) -> bool:
        """True if credentials are registered (nothing is decrypted)."""
        return await self._repo.get() is not None

    async def load_plain(self) -> PlainCredentials | None:
        """Decrypt the credentials; raises ``CredentialsUndecryptable`` on a key mismatch."""
        stored = await self._repo.get()
        if stored is None:
            return None
        plain = PlainCredentials(
            api_key=self._cipher.decrypt(stored.api_key_enc),
            api_secret=self._cipher.decrypt(stored.api_secret_enc),
        )
        register_secret(plain.api_key)
        register_secret(plain.api_secret)
        return plain
