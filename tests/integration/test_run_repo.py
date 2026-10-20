"""Run repository against a real MongoDB: lock index, paging, recovery and retention."""

from datetime import UTC, datetime, timedelta

import pytest

from alpaca_gatherer.domain.errors import RunInProgress
from alpaca_gatherer.domain.runs import (
    Run,
    RunCounts,
    RunError,
    RunErrorCode,
    RunStatus,
    RunTrigger,
    RunWindow,
)
from alpaca_gatherer.infrastructure.db.client import Collections, MongoDatabase
from alpaca_gatherer.infrastructure.db.indexes import ensure_indexes
from alpaca_gatherer.infrastructure.db.run_repo import MongoRunRepository

T0 = datetime(2026, 10, 1, tzinfo=UTC)
FAIL = RunError(RunErrorCode.COLLECTOR_UNAVAILABLE, "down")
SKIP = RunError(RunErrorCode.SKIPPED_CONCURRENT_RUN, "busy")


def run(i: int) -> Run:
    return Run.start(
        f"run-{i:03d}", RunTrigger.MANUAL, T0 + timedelta(hours=i), {"price": {"p": 1.0}}
    )


@pytest.fixture
async def repo(db: MongoDatabase, collections: Collections) -> MongoRunRepository:
    await ensure_indexes(db, collections)
    return MongoRunRepository(db, collections)


async def test_second_running_run_is_rejected(repo: MongoRunRepository) -> None:
    await repo.insert_running(run(1))
    with pytest.raises(RunInProgress) as info:
        await repo.insert_running(run(2))
    assert info.value.active_run_id == "run-001"
    active = await repo.active()
    assert active is not None
    await repo.finish(active.fail(T0, FAIL))
    await repo.insert_running(run(3))  # the lock is free again


async def test_round_trip_get_and_finish(repo: MongoRunRepository) -> None:
    first = run(1)
    await repo.insert_running(first)
    window = RunWindow(T0 - timedelta(days=28), T0, 20)
    done = first.succeed(T0 + timedelta(hours=2), RunCounts(3, 1, 2, {"not_tradable": 2}), window)
    await repo.finish(done)
    assert await repo.get("run-001") == done
    assert await repo.get("missing") is None
    assert await repo.latest_succeeded() == done


async def test_list_newest_first_with_total(repo: MongoRunRepository) -> None:
    for i in range(5):
        await repo.insert_terminal(run(i).fail(T0, FAIL))
    page = await repo.list(limit=2, offset=1)
    assert [r.run_id for r in page] == ["run-003", "run-002"]
    assert await repo.count() == 5


async def test_mark_running_as_interrupted(repo: MongoRunRepository) -> None:
    await repo.insert_terminal(run(1).fail(T0, FAIL))
    await repo.insert_running(run(2))
    now = T0 + timedelta(days=1)
    assert await repo.mark_running_as_interrupted(now) == ["run-002"]
    interrupted = await repo.get("run-002")
    assert interrupted is not None
    assert interrupted.status is RunStatus.FAILED
    assert interrupted.error == RunError(
        RunErrorCode.INTERRUPTED_BY_RESTART, "interrupted by service restart"
    )
    assert interrupted.finished_at == now
    assert await repo.active() is None


async def test_latest_succeeded_picks_newest(repo: MongoRunRepository) -> None:
    window = RunWindow(T0, T0, 20)
    for i in (1, 3, 2):
        await repo.insert_terminal(
            run(i).succeed(T0 + timedelta(hours=i), RunCounts(0, 0, 0), window)
        )
    latest = await repo.latest_succeeded()
    assert latest is not None
    assert latest.run_id == "run-003"


async def test_prune_pools_are_independent(repo: MongoRunRepository) -> None:
    for i in range(55):
        await repo.insert_terminal(run(i).fail(T0, FAIL))
    for i in range(30):
        await repo.insert_terminal(
            Run.skipped(f"skip-{i:03d}", T0 + timedelta(days=5, hours=i), {}, SKIP)
        )
    await repo.insert_running(run(200))
    deleted = await repo.prune(limit=50, skip_limit=20)
    assert deleted == 5 + 10
    remaining = await repo.list(limit=1000, offset=0)
    executed = {r.run_id for r in remaining if not r.is_skip_record}
    skips = {r.run_id for r in remaining if r.is_skip_record}
    assert executed == {f"run-{i:03d}" for i in range(5, 55)} | {"run-200"}
    assert skips == {f"skip-{i:03d}" for i in range(10, 30)}


async def test_thirty_skips_do_not_evict_fifty_executed(repo: MongoRunRepository) -> None:
    for i in range(50):
        await repo.insert_terminal(run(i).fail(T0, FAIL))
    for i in range(30):
        await repo.insert_terminal(
            Run.skipped(f"skip-{i:03d}", T0 + timedelta(days=9, hours=i), {}, SKIP)
        )
    await repo.prune(limit=50)
    executed = [r for r in await repo.list(limit=1000, offset=0) if not r.is_skip_record]
    assert len(executed) == 50
