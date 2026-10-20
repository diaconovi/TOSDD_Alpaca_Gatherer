"""Staging writes and the atomic ``renameCollection`` swap against a real MongoDB."""

import asyncio

import pytest
from pymongo.errors import OperationFailure

from alpaca_gatherer.domain.mapping import InstrumentMapping
from alpaca_gatherer.infrastructure.db.client import Collections, MongoDatabase
from alpaca_gatherer.infrastructure.db.indexes import ensure_indexes
from alpaca_gatherer.infrastructure.db.mapping_repo import MongoMappingRepository
from tests.samples import matched, unmatched


@pytest.fixture
async def repo(db: MongoDatabase, collections: Collections) -> MongoMappingRepository:
    await ensure_indexes(db, collections)
    return MongoMappingRepository(db, collections)


def snapshot(run_id: str, size: int) -> list[InstrumentMapping]:
    return [matched(f"E{i:04d}", f"S{i:04d}", run_id=run_id) for i in range(size)]


async def test_write_staging_creates_indexed_collection(
    repo: MongoMappingRepository, db: MongoDatabase, collections: Collections
) -> None:
    await repo.write_staging("r1", [matched(), unmatched()])
    staging = db[collections.staging("r1")]
    assert await staging.count_documents({}) == 2
    names = {ix["name"] for ix in await (await staging.list_indexes()).to_list()}
    assert {"capital_epic_unique", "matched_alpaca_symbol_unique"} <= names


async def test_swap_replaces_live_mapping(
    repo: MongoMappingRepository, db: MongoDatabase, collections: Collections
) -> None:
    await repo.write_staging("r1", [matched(run_id="r1")])
    await repo.swap("r1")
    await repo.write_staging("r2", [unmatched(run_id="r2")])
    await repo.swap("r2")
    assert await repo.find_by_epic("BRKB") is None
    record = await repo.find_by_epic("APPL")
    assert record is not None
    assert record.run_id == "r2"
    assert collections.staging("r2") not in await db.list_collection_names()
    names = {ix["name"] for ix in await (await db[collections.mapping].list_indexes()).to_list()}
    assert "matched_alpaca_symbol_unique" in names


async def test_concurrent_reader_sees_whole_old_or_whole_new_snapshot(
    repo: MongoMappingRepository, db: MongoDatabase, collections: Collections
) -> None:
    size = 300
    await repo.write_staging("old", snapshot("old", size))
    await repo.swap("old")
    await repo.write_staging("new", snapshot("new", size))
    live = db[collections.mapping]
    observed: list[set[str]] = []
    stop = asyncio.Event()

    lookups: list[str] = []

    async def reader() -> None:
        while not stop.is_set():
            try:
                docs = await live.find({}, projection={"run_id": 1}).to_list()
            except OperationFailure as exc:
                if exc.code != 175:  # 175: the swap killed this scan; it saw nothing partial
                    raise
                continue
            if docs:
                assert len(docs) == size
                observed.append({d["run_id"] for d in docs})
            await asyncio.sleep(0)

    async def looker() -> None:
        while not stop.is_set():
            record = await repo.find_by_epic("E0150")  # the repository retries killed reads
            assert record is not None
            lookups.append(record.run_id)
            await asyncio.sleep(0)

    tasks = [asyncio.create_task(reader()), asyncio.create_task(looker())]
    await asyncio.sleep(0.05)
    await repo.swap("new")
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.gather(*tasks)
    assert observed
    assert all(runs in ({"old"}, {"new"}) for runs in observed)
    assert observed[-1] == {"new"}
    assert set(lookups) <= {"old", "new"}
    assert lookups[-1] == "new"


async def test_drop_staging_and_drop_all(
    repo: MongoMappingRepository, db: MongoDatabase, collections: Collections
) -> None:
    for run_id in ("a", "b", "c"):
        await repo.write_staging(run_id, [matched()])
    await repo.drop_staging("a")
    dropped = await repo.drop_all_staging()
    assert sorted(dropped) == [collections.staging("b"), collections.staging("c")]
    remaining = await db.list_collection_names()
    assert not [n for n in remaining if n.startswith(collections.staging_prefix)]
