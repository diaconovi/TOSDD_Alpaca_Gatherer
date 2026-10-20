"""Mapping repository reads and mapping indexes against a real MongoDB."""

import pytest
from pymongo.errors import DuplicateKeyError

from alpaca_gatherer.domain.mapping import MatchStatus
from alpaca_gatherer.infrastructure.db.client import Collections, MongoDatabase
from alpaca_gatherer.infrastructure.db.indexes import ensure_indexes
from alpaca_gatherer.infrastructure.db.mapping_repo import MongoMappingRepository, to_document
from tests.samples import ambiguous, matched, unmatched


@pytest.fixture
async def repo(db: MongoDatabase, collections: Collections) -> MongoMappingRepository:
    await ensure_indexes(db, collections)
    return MongoMappingRepository(db, collections)


async def seed(db: MongoDatabase, collections: Collections) -> None:
    docs = [to_document(r) for r in (matched(), unmatched(), ambiguous())]
    await db[collections.mapping].insert_many(docs)


async def test_find_by_epic_round_trips(
    db: MongoDatabase, collections: Collections, repo: MongoMappingRepository
) -> None:
    await seed(db, collections)
    assert await repo.find_by_epic("BRKB") == matched()
    assert await repo.find_by_epic("APPL") == unmatched()
    assert await repo.find_by_epic("WSOB") == ambiguous()
    assert await repo.find_by_epic("brkb") is None


async def test_find_matched_by_symbol(
    db: MongoDatabase, collections: Collections, repo: MongoMappingRepository
) -> None:
    await seed(db, collections)
    found = await repo.find_matched_by_symbol("BRK.B")
    assert found is not None
    assert found.capital_epic == "BRKB"
    assert found.status is MatchStatus.MATCHED
    assert await repo.find_matched_by_symbol("WSO") is None


async def test_unique_partial_index_on_matched_symbol(
    db: MongoDatabase, collections: Collections, repo: MongoMappingRepository
) -> None:
    live = db[collections.mapping]
    await live.insert_one(to_document(matched("BRKB", "BRK.B")))
    with pytest.raises(DuplicateKeyError):
        await live.insert_one(to_document(matched("BRKBUS", "BRK.B")))
    await live.insert_one(to_document(ambiguous("X1", ("WSO", "WSO.B"))))
    await live.insert_one(to_document(ambiguous("X2", ("WSO", "WSO.B"))))
    assert await live.count_documents({}) == 3


async def test_unique_epic_index(
    db: MongoDatabase, collections: Collections, repo: MongoMappingRepository
) -> None:
    await db[collections.mapping].insert_one(to_document(unmatched("APPL")))
    with pytest.raises(DuplicateKeyError):
        await db[collections.mapping].insert_one(to_document(unmatched("APPL")))


async def test_has_snapshot(
    db: MongoDatabase, collections: Collections, repo: MongoMappingRepository
) -> None:
    absent = MongoMappingRepository(db, Collections(collections.mapping + "_absent"))
    assert await absent.has_snapshot() is False
    assert await repo.has_snapshot() is False  # indexed but empty
    await seed(db, collections)
    assert await repo.has_snapshot() is True
