"""MongoDB run repository: run history, the single-run lock and retention.

The unique partial index on ``status`` (``status = "running"``) makes a second ``running`` insert
fail with ``DuplicateKeyError``, which is the authoritative "one run at a time" guarantee.
"""

import builtins
from datetime import datetime
from typing import Any

from pymongo import DESCENDING
from pymongo.errors import DuplicateKeyError

from alpaca_gatherer.domain.errors import RunInProgress
from alpaca_gatherer.domain.runs import (
    SKIP_HISTORY_LIMIT,
    Run,
    RunCounts,
    RunError,
    RunErrorCode,
    RunStatus,
    RunTrigger,
    RunWindow,
)
from alpaca_gatherer.infrastructure.db.client import (
    Collections,
    Document,
    MongoCollection,
    MongoDatabase,
)

__all__ = ["MongoRunRepository", "run_from_document", "run_to_document"]

INTERRUPTED_DETAIL = "interrupted by service restart"
_NEWEST_FIRST = [("started_at", DESCENDING)]


def run_to_document(run: Run) -> Document:
    """Convert a run into its BSON document (``_id`` is the run id)."""
    counts = run.counts
    return {
        "_id": run.run_id,
        "run_id": run.run_id,
        "trigger": run.trigger.value,
        "status": run.status.value,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "price_window_end": run.price_window_end,
        "window": (
            {"start": run.window.start, "end": run.window.end, "sessions": run.window.sessions}
            if run.window
            else None
        ),
        "thresholds": {group: dict(values) for group, values in run.thresholds.items()},
        "counts": (
            {
                "matched": counts.matched,
                "ambiguous": counts.ambiguous,
                "unmatched": counts.unmatched,
                "total": counts.total,
                "by_reason": dict(counts.by_reason),
            }
            if counts
            else None
        ),
        "error": {"code": run.error.code.value, "detail": run.error.detail} if run.error else None,
    }


def run_from_document(doc: Document) -> Run:
    """Convert a BSON document back into a run."""
    window: dict[str, Any] | None = doc.get("window")
    counts: dict[str, Any] | None = doc.get("counts")
    error: dict[str, Any] | None = doc.get("error")
    return Run(
        run_id=doc["_id"],
        trigger=RunTrigger(doc["trigger"]),
        status=RunStatus(doc["status"]),
        started_at=doc["started_at"],
        finished_at=doc.get("finished_at"),
        price_window_end=doc["price_window_end"],
        window=RunWindow(window["start"], window["end"], window["sessions"]) if window else None,
        thresholds=doc.get("thresholds") or {},
        counts=(
            RunCounts(
                matched=counts["matched"],
                ambiguous=counts["ambiguous"],
                unmatched=counts["unmatched"],
                by_reason=counts.get("by_reason") or {},
            )
            if counts
            else None
        ),
        error=RunError(RunErrorCode(error["code"]), error["detail"]) if error else None,
    )


class MongoRunRepository:
    """Implements ``RunRepository``."""

    def __init__(self, db: MongoDatabase, collections: Collections) -> None:
        self._runs: MongoCollection = db[collections.runs]

    async def insert_running(self, run: Run) -> None:
        """Insert a running run; ``RunInProgress`` if the lock index rejects it."""
        try:
            await self._runs.insert_one(run_to_document(run))
        except DuplicateKeyError:
            active = await self.active()
            raise RunInProgress(active.run_id if active else "unknown") from None

    async def insert_terminal(self, run: Run) -> None:
        """Insert a run that is already terminal (a recorded scheduled skip)."""
        await self._runs.insert_one(run_to_document(run))

    async def finish(self, run: Run) -> None:
        """Store the terminal state of a run."""
        await self._runs.replace_one({"_id": run.run_id}, run_to_document(run), upsert=True)

    async def get(self, run_id: str) -> Run | None:
        """One run by id."""
        doc = await self._runs.find_one({"_id": run_id})
        return run_from_document(doc) if doc else None

    async def list(self, limit: int, offset: int) -> builtins.list[Run]:
        """A page of runs, newest first."""
        cursor = self._runs.find({}).sort(_NEWEST_FIRST).skip(offset).limit(limit)
        return [run_from_document(doc) async for doc in cursor]

    async def count(self) -> int:
        """Number of retained runs."""
        return await self._runs.count_documents({})

    async def active(self) -> Run | None:
        """The running run, if any."""
        doc = await self._runs.find_one({"status": RunStatus.RUNNING.value})
        return run_from_document(doc) if doc else None

    async def latest_succeeded(self) -> Run | None:
        """The newest succeeded run."""
        doc = await self._runs.find_one({"status": RunStatus.SUCCEEDED.value}, sort=_NEWEST_FIRST)
        return run_from_document(doc) if doc else None

    async def mark_running_as_interrupted(self, now: datetime) -> builtins.list[str]:
        """Fail every running run with ``interrupted_by_restart``; return their ids."""
        ids = [doc["_id"] async for doc in self._runs.find({"status": RunStatus.RUNNING.value})]
        if ids:
            await self._runs.update_many(
                {"_id": {"$in": ids}, "status": RunStatus.RUNNING.value},
                {
                    "$set": {
                        "status": RunStatus.FAILED.value,
                        "finished_at": now,
                        "error": {
                            "code": RunErrorCode.INTERRUPTED_BY_RESTART.value,
                            "detail": INTERRUPTED_DETAIL,
                        },
                    }
                },
            )
        return ids

    async def prune(self, limit: int, skip_limit: int = SKIP_HISTORY_LIMIT) -> int:
        """Keep the newest ``limit`` executed runs and ``skip_limit`` skip records."""
        terminal = {"$ne": RunStatus.RUNNING.value}
        skipped = RunErrorCode.SKIPPED_CONCURRENT_RUN.value
        pools = (
            ({"status": terminal, "error.code": {"$ne": skipped}}, limit),
            ({"status": terminal, "error.code": skipped}, skip_limit),
        )
        doomed: builtins.list[str] = []
        for query, keep in pools:
            cursor = self._runs.find(query, projection={"_id": 1}).sort(_NEWEST_FIRST).skip(keep)
            doomed += [doc["_id"] async for doc in cursor]
        if not doomed:
            return 0
        result = await self._runs.delete_many({"_id": {"$in": doomed}})
        return result.deleted_count
