"""Credential use cases with fakes (FR-024 to FR-026)."""

from collections.abc import Iterator
from datetime import timedelta

import pytest

from alpaca_gatherer.application.credentials import (
    CredentialsProvider,
    RegisterCredentials,
    UpdateCredentials,
)
from alpaca_gatherer.domain.credentials import EncryptedCredentials, PlainCredentials
from alpaca_gatherer.domain.errors import CredentialsExist, CredentialsNotFound
from alpaca_gatherer.logging_setup import mask, reset_secrets
from tests.fakes import FrozenClock, InMemoryCredentialRepository, ReversingCipher


@pytest.fixture(autouse=True)
def _clean_secrets() -> Iterator[None]:
    reset_secrets()
    yield
    reset_secrets()


@pytest.fixture
def repo() -> InMemoryCredentialRepository:
    return InMemoryCredentialRepository()


async def test_register_stores_two_ciphertexts_and_times(
    repo: InMemoryCredentialRepository, clock: FrozenClock
) -> None:
    await RegisterCredentials(repo, ReversingCipher(), clock)("key-123", "secret-456")
    stored = repo.stored
    assert stored is not None
    assert stored.api_key_enc == "enc:321-yek"
    assert stored.api_secret_enc == "enc:654-terces"
    assert stored.created_at == stored.updated_at == clock.now()


async def test_second_register_conflicts(
    repo: InMemoryCredentialRepository, clock: FrozenClock
) -> None:
    register = RegisterCredentials(repo, ReversingCipher(), clock)
    await register("key-123", "secret-456")
    with pytest.raises(CredentialsExist):
        await register("other", "other")


async def test_update_before_register_is_not_found(
    repo: InMemoryCredentialRepository, clock: FrozenClock
) -> None:
    with pytest.raises(CredentialsNotFound):
        await UpdateCredentials(repo, ReversingCipher(), clock)("k", "s")


async def test_update_overwrites_without_decrypting_old_values(clock: FrozenClock) -> None:
    created = clock.now()
    repo = InMemoryCredentialRepository(
        EncryptedCredentials("undecryptable-old", "undecryptable-old", created, created)
    )
    clock.advance(timedelta(hours=1))
    await UpdateCredentials(repo, ReversingCipher(), clock)("new-key", "new-secret")
    assert repo.stored == EncryptedCredentials(
        "enc:yek-wen", "enc:terces-wen", created, clock.now()
    )


async def test_load_plain_none_when_unregistered(repo: InMemoryCredentialRepository) -> None:
    provider = CredentialsProvider(repo, ReversingCipher())
    assert await provider.load_plain() is None
    assert await provider.exists() is False


async def test_load_plain_decrypts_and_registers_secrets(
    repo: InMemoryCredentialRepository, clock: FrozenClock
) -> None:
    await RegisterCredentials(repo, ReversingCipher(), clock)("key-123", "secret-456")
    provider = CredentialsProvider(repo, ReversingCipher())
    assert await provider.exists() is True
    assert await provider.load_plain() == PlainCredentials("key-123", "secret-456")
    assert mask("key-123 / secret-456") == "*** / ***"
