"""MongoDB schedule repository: at most one document ``_id: "schedule"`` (data-model.md §3)."""

from datetime import datetime

from alpaca_gatherer.domain.scheduling.definitions import (
    CronSchedule,
    OneTimeSchedule,
    RecurringSchedule,
    ScheduleDefinition,
)
from alpaca_gatherer.infrastructure.db.client import Collections, Document, MongoDatabase

__all__ = ["MongoScheduleRepository", "schedule_from_document", "schedule_to_document"]

_ID = "schedule"


def schedule_to_document(definition: ScheduleDefinition, updated_at: datetime) -> Document:
    """The stored form of a schedule."""
    doc: Document = {
        "_id": _ID,
        "kind": None,
        "cron": None,
        "day": None,
        "time": None,
        "date": None,
        "timezone": definition.timezone,
        "updated_at": updated_at,
    }
    match definition:
        case CronSchedule(cron=cron):
            doc.update(kind="cron", cron=cron)
        case RecurringSchedule(day=day, time=time):
            doc.update(kind="recurring", day=day, time=time)
        case OneTimeSchedule(date=date):
            doc.update(kind="one_time", date=date)
    return doc


def schedule_from_document(doc: Document) -> ScheduleDefinition:
    """Rebuild a schedule from its stored form."""
    timezone: str = doc.get("timezone") or "UTC"
    match doc["kind"]:
        case "cron":
            return CronSchedule(doc["cron"], timezone)
        case "recurring":
            return RecurringSchedule(doc["day"], doc["time"], timezone)
        case "one_time":
            return OneTimeSchedule(doc["date"], timezone)
        case other:
            raise ValueError(f"unknown schedule kind {other!r}")


class MongoScheduleRepository:
    """Implements ``ScheduleRepository``."""

    def __init__(self, db: MongoDatabase, collections: Collections) -> None:
        self._collection = db[collections.schedule]

    async def get(self) -> ScheduleDefinition | None:
        """The stored schedule, if any."""
        doc = await self._collection.find_one({"_id": _ID})
        return schedule_from_document(doc) if doc else None

    async def put(self, definition: ScheduleDefinition, updated_at: datetime) -> None:
        """Replace the stored schedule."""
        await self._collection.replace_one(
            {"_id": _ID}, schedule_to_document(definition, updated_at), upsert=True
        )

    async def delete(self) -> None:
        """Remove the stored schedule."""
        await self._collection.delete_one({"_id": _ID})
