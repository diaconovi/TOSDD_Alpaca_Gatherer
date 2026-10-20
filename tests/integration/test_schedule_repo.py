"""Schedule repository against a real MongoDB (data-model.md §3)."""

from datetime import UTC, datetime

import pytest

from alpaca_gatherer.domain.scheduling.definitions import (
    CronSchedule,
    OneTimeSchedule,
    RecurringSchedule,
)
from alpaca_gatherer.infrastructure.db.client import Collections, MongoDatabase
from alpaca_gatherer.infrastructure.db.schedule_repo import MongoScheduleRepository

T0 = datetime(2026, 10, 18, 12, tzinfo=UTC)


@pytest.fixture
def repo(db: MongoDatabase, collections: Collections) -> MongoScheduleRepository:
    return MongoScheduleRepository(db, collections)


@pytest.mark.parametrize(
    "definition",
    [
        CronSchedule("*/5 * * * *"),
        RecurringSchedule("mon-fri", "18:00", "America/New_York"),
        OneTimeSchedule(datetime(2026, 12, 1, 19, 48, 19, tzinfo=UTC), "Asia/Tokyo"),
    ],
)
async def test_round_trip(
    repo: MongoScheduleRepository,
    definition: CronSchedule | RecurringSchedule | OneTimeSchedule,
) -> None:
    assert await repo.get() is None
    await repo.put(definition, T0)
    assert await repo.get() == definition


async def test_single_document_shape_and_upsert(
    repo: MongoScheduleRepository, db: MongoDatabase, collections: Collections
) -> None:
    await repo.put(CronSchedule("0 * * * *"), T0)
    await repo.put(RecurringSchedule("sat", "06:00", "UTC"), T0)
    docs = await db[collections.schedule].find({}).to_list()
    assert len(docs) == 1
    doc = docs[0]
    assert doc["_id"] == "schedule"
    assert set(doc) == {"_id", "kind", "cron", "day", "time", "date", "timezone", "updated_at"}
    assert (doc["kind"], doc["cron"], doc["day"], doc["time"]) == (
        "recurring",
        None,
        "sat",
        "06:00",
    )
    assert doc["updated_at"] == T0


async def test_one_time_date_stored_as_utc(
    repo: MongoScheduleRepository, db: MongoDatabase, collections: Collections
) -> None:
    when = datetime(2026, 12, 1, 19, 48, 19, tzinfo=UTC)
    await repo.put(OneTimeSchedule(when, "Asia/Tokyo"), T0)
    doc = await db[collections.schedule].find_one({})
    assert doc is not None
    assert doc["date"] == when
    assert doc["timezone"] == "Asia/Tokyo"


async def test_delete(repo: MongoScheduleRepository) -> None:
    await repo.put(CronSchedule("0 * * * *"), T0)
    await repo.delete()
    assert await repo.get() is None
    await repo.delete()  # deleting nothing is fine
