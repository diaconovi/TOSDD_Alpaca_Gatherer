"""MongoDB credential repository: one document ``_id: "alpaca"`` (data-model.md §4)."""

from datetime import datetime

from pymongo.errors import DuplicateKeyError

from alpaca_gatherer.domain.credentials import EncryptedCredentials
from alpaca_gatherer.domain.errors import CredentialsExist, CredentialsNotFound
from alpaca_gatherer.infrastructure.db.client import Collections, MongoDatabase

__all__ = ["MongoCredentialRepository"]

_ID = "alpaca"


class MongoCredentialRepository:
    """Implements ``CredentialRepository``; stores ciphertext only."""

    def __init__(self, db: MongoDatabase, collections: Collections) -> None:
        self._collection = db[collections.credentials]

    async def insert(self, credentials: EncryptedCredentials) -> None:
        """Store credentials; ``CredentialsExist`` if a document already exists."""
        try:
            await self._collection.insert_one(
                {
                    "_id": _ID,
                    "api_key_enc": credentials.api_key_enc,
                    "api_secret_enc": credentials.api_secret_enc,
                    "created_at": credentials.created_at,
                    "updated_at": credentials.updated_at,
                }
            )
        except DuplicateKeyError:
            raise CredentialsExist() from None

    async def update(self, api_key_enc: str, api_secret_enc: str, updated_at: datetime) -> None:
        """Replace both ciphertexts; ``CredentialsNotFound`` if nothing is stored."""
        result = await self._collection.update_one(
            {"_id": _ID},
            {
                "$set": {
                    "api_key_enc": api_key_enc,
                    "api_secret_enc": api_secret_enc,
                    "updated_at": updated_at,
                }
            },
        )
        if result.matched_count == 0:
            raise CredentialsNotFound()

    async def get(self) -> EncryptedCredentials | None:
        """Return the stored credentials, if any."""
        doc = await self._collection.find_one({"_id": _ID})
        if doc is None:
            return None
        return EncryptedCredentials(
            api_key_enc=doc["api_key_enc"],
            api_secret_enc=doc["api_secret_enc"],
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )
