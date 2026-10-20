"""Index creation at startup.

The unique partial index on ``M_runs.status`` (``status = running``) is the single-run lock
(research R6); the unique partial index on ``M.alpaca_symbol`` keeps matched symbols one-to-one.
"""

from pymongo import ASCENDING, DESCENDING, IndexModel

from alpaca_gatherer.infrastructure.db.client import Collections, MongoCollection, MongoDatabase

__all__ = ["create_mapping_indexes", "ensure_indexes"]

MAPPING_INDEXES = [
    IndexModel([("capital_epic", ASCENDING)], unique=True, name="capital_epic_unique"),
    IndexModel(
        [("alpaca_symbol", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": "matched"},
        name="matched_alpaca_symbol_unique",
    ),
]

RUN_INDEXES = [
    IndexModel(
        [("status", ASCENDING)],
        unique=True,
        partialFilterExpression={"status": "running"},
        name="single_running_run",
    ),
    IndexModel([("started_at", DESCENDING)], name="started_at_desc"),
]


async def create_mapping_indexes(collection: MongoCollection) -> None:
    """Create the mapping indexes on a live or staging mapping collection."""
    await collection.create_indexes(MAPPING_INDEXES)


async def ensure_indexes(db: MongoDatabase, collections: Collections) -> None:
    """Create every index the service relies on (idempotent)."""
    await create_mapping_indexes(db[collections.mapping])
    await db[collections.runs].create_indexes(RUN_INDEXES)
