"""Startup recovery (FR-012b)."""

from datetime import UTC, datetime, timedelta

from alpaca_gatherer.application.runs.recover import RecoverOnStartup
from alpaca_gatherer.domain.runs import Run, RunError, RunErrorCode, RunStatus, RunTrigger
from tests.fakes import FrozenClock, InMemoryMappingRepository, InMemoryRunRepository
from tests.samples import matched

T0 = datetime(2026, 10, 18, 9, tzinfo=UTC)


async def test_running_runs_fail_staging_dropped_mapping_kept() -> None:
    runs = InMemoryRunRepository()
    mappings = InMemoryMappingRepository([matched(run_id="previous")])
    await mappings.write_staging("crashed", [matched(run_id="crashed")])
    await runs.insert_running(Run.start("crashed", RunTrigger.MANUAL, T0, {}))
    finished = Run.start("done", RunTrigger.MANUAL, T0 - timedelta(days=1), {})
    await runs.insert_terminal(finished.fail(T0, RunError(RunErrorCode.INTERNAL_ERROR, "x")))
    clock = FrozenClock(T0 + timedelta(minutes=5))

    interrupted = await RecoverOnStartup(runs, mappings, clock)()

    assert interrupted == ["crashed"]
    run = await runs.get("crashed")
    assert run is not None
    assert run.status is RunStatus.FAILED
    assert run.error == RunError(
        RunErrorCode.INTERRUPTED_BY_RESTART, "interrupted by service restart"
    )
    assert run.finished_at == clock.now()
    assert mappings.staging == {}
    record = await mappings.find_by_epic("BRKB")
    assert record is not None
    assert record.run_id == "previous"
    assert await runs.active() is None
    assert len(runs.runs) == 2  # nothing new was started


async def test_nothing_to_recover() -> None:
    runs = InMemoryRunRepository()
    assert await RecoverOnStartup(runs, InMemoryMappingRepository(), FrozenClock())() == []
