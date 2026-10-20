"""MongoDB client factory and collection naming.

>>> c = Collections("mapping")
>>> c.runs, c.schedule, c.credentials, c.staging("r1")
('mapping_runs', 'mapping_schedule', 'mapping_credentials', 'mapping_staging_r1')
"""

from dataclasses import dataclass
from datetime import UTC
from typing import Any

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase

__all__ = [
    "Collections",
    "Document",
    "MongoClient",
    "MongoCollection",
    "MongoDatabase",
    "create_mongo_client",
]

# BSON documents are untyped at the driver boundary; repositories convert them to domain types.
type Document = dict[str, Any]
type MongoClient = AsyncMongoClient[Document]
type MongoDatabase = AsyncDatabase[Document]
type MongoCollection = AsyncCollection[Document]


def create_mongo_client(uri: str, server_selection_timeout_ms: int = 5000) -> MongoClient:
    """Create an async client that returns aware UTC datetimes."""
    return AsyncMongoClient(
        uri,
        tz_aware=True,
        tzinfo=UTC,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
        appname="alpaca-gatherer",
    )


@dataclass(frozen=True, slots=True)
class Collections:
    """Names of every collection, derived from ``MONGO_MAPPING_COLLECTION``."""

    mapping: str

    @property
    def runs(self) -> str:
        """Run history collection."""
        return f"{self.mapping}_runs"

    @property
    def schedule(self) -> str:
        """Single-document schedule collection."""
        return f"{self.mapping}_schedule"

    @property
    def credentials(self) -> str:
        """Single-document credentials collection."""
        return f"{self.mapping}_credentials"

    @property
    def staging_prefix(self) -> str:
        """Prefix shared by every staging collection."""
        return f"{self.mapping}_staging_"

    def staging(self, run_id: str) -> str:
        """Staging collection of one run."""
        return f"{self.staging_prefix}{run_id}"
