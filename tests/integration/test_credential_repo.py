"""Credential repository against a real MongoDB (data-model.md §4)."""

from datetime import UTC, datetime

import pytest

from alpaca_gatherer.domain.credentials import EncryptedCredentials
from alpaca_gatherer.domain.errors import CredentialsExist, CredentialsNotFound
from alpaca_gatherer.infrastructure.db.client import Collections, MongoDatabase
from alpaca_gatherer.infrastructure.db.credential_repo import MongoCredentialRepository

T0 = datetime(2026, 10, 18, 12, tzinfo=UTC)
T1 = datetime(2026, 10, 18, 13, tzinfo=UTC)


@pytest.fixture
def repo(db: MongoDatabase, collections: Collections) -> MongoCredentialRepository:
    return MongoCredentialRepository(db, collections)


async def test_insert_uses_fixed_id_and_exact_fields(
    repo: MongoCredentialRepository, db: MongoDatabase, collections: Collections
) -> None:
    await repo.insert(EncryptedCredentials("k-enc", "s-enc", T0, T0))
    doc = await db[collections.credentials].find_one({})
    assert doc is not None
    assert doc["_id"] == "alpaca"
    assert set(doc) - {"_id"} == {"api_key_enc", "api_secret_enc", "created_at", "updated_at"}
    assert await repo.get() == EncryptedCredentials("k-enc", "s-enc", T0, T0)


async def test_duplicate_insert_conflicts(repo: MongoCredentialRepository) -> None:
    await repo.insert(EncryptedCredentials("k", "s", T0, T0))
    with pytest.raises(CredentialsExist):
        await repo.insert(EncryptedCredentials("k2", "s2", T1, T1))


async def test_update_without_document_is_not_found(repo: MongoCredentialRepository) -> None:
    with pytest.raises(CredentialsNotFound):
        await repo.update("k", "s", T1)
    assert await repo.get() is None


async def test_update_replaces_values_and_keeps_created_at(
    repo: MongoCredentialRepository,
) -> None:
    await repo.insert(EncryptedCredentials("k", "s", T0, T0))
    await repo.update("k2", "s2", T1)
    assert await repo.get() == EncryptedCredentials("k2", "s2", T0, T1)
