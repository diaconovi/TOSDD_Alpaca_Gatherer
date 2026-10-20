"""Schedule use cases with fakes."""

from datetime import UTC, datetime, timedelta

import pytest

from alpaca_gatherer.application.credentials import CredentialsProvider
from alpaca_gatherer.application.runs.start_run import StartRun
from alpaca_gatherer.application.schedule import (
    GetSchedule,
    OnScheduledFire,
    RestoreScheduleOnStartup,
    SetSchedule,
)
from alpaca_gatherer.domain.errors import ScheduleValidationError
from alpaca_gatherer.domain.runs import Run, RunCounts, RunErrorCode, RunTrigger, RunWindow
from alpaca_gatherer.domain.scheduling.definitions import (
    CronSchedule,
    OneTimeSchedule,
    RecurringSchedule,
    ScheduleDefinition,
)
from alpaca_gatherer.domain.thresholds import Thresholds
from tests.fakes import (
    FakeJobScheduler,
    FrozenClock,
    InMemoryCredentialRepository,
    InMemoryRunRepository,
    InMemoryScheduleRepository,
    ReversingCipher,
)

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


class Setup:
    def __init__(self, stored: ScheduleDefinition | None = None) -> None:
        self.clock = FrozenClock(NOW)
        self.schedules = InMemoryScheduleRepository(stored)
        self.runs = InMemoryRunRepository()
        self.scheduler = FakeJobScheduler()
        self.started: list[Run] = []

        async def execute(run: Run) -> Run:
            self.started.append(run)
            return run

        self.start_run = StartRun(
            credentials=CredentialsProvider(InMemoryCredentialRepository(), ReversingCipher()),
            runs=self.runs,
            execute=execute,
            clock=self.clock,
            thresholds=Thresholds.defaults(),
            history_limit=50,
        )
        self.on_fire = OnScheduledFire(self.start_run, self.schedules)
        self.view = GetSchedule(self.schedules, self.runs, self.scheduler, self.clock)
        self.set = SetSchedule(self.schedules, self.scheduler, self.clock, self.on_fire, self.view)
        self.restore = RestoreScheduleOnStartup(
            self.schedules, self.scheduler, self.clock, self.on_fire
        )


async def test_set_persists_and_replaces_job() -> None:
    s = Setup()
    view = await s.set(
        {"schedule": {"day": "mon-fri", "time": "18:00"}, "timezone": "America/New_York"}
    )
    expected = RecurringSchedule("mon-fri", "18:00", "America/New_York")
    assert s.schedules.definition == expected
    assert s.schedules.updated_at == NOW
    assert s.scheduler.job is not None
    assert s.scheduler.job[0] == expected
    assert view.schedule == expected
    assert view.timezone == "America/New_York"
    assert view.next_run is not None
    assert view.next_run.utcoffset() == timedelta(hours=-4)


async def test_invalid_input_touches_nothing() -> None:
    s = Setup(CronSchedule("0 * * * *"))
    s.scheduler.replace_job(CronSchedule("0 * * * *"), s.on_fire)
    with pytest.raises(ScheduleValidationError):
        await s.set({"cron": "61 * * * *"})
    with pytest.raises(ScheduleValidationError):
        await s.set({"schedule": {"date": "2026-01-01T00:00:00Z"}})
    assert s.schedules.writes == 0
    assert s.schedules.definition == CronSchedule("0 * * * *")
    assert s.scheduler.job is not None


async def test_clear_deletes_document_and_job() -> None:
    s = Setup(CronSchedule("0 * * * *"))
    s.scheduler.replace_job(CronSchedule("0 * * * *"), s.on_fire)
    view = await s.set({"schedule": None})
    assert s.schedules.definition is None
    assert s.scheduler.job is None
    assert (view.schedule, view.next_run, view.timezone) == (None, None, "UTC")


async def test_view_reports_last_succeeded_run() -> None:
    s = Setup()
    run = Run.start("r1", RunTrigger.MANUAL, NOW - timedelta(hours=2), {})
    finished = NOW - timedelta(hours=1)
    await s.runs.insert_terminal(run.succeed(finished, RunCounts(1, 0, 0), RunWindow(NOW, NOW, 20)))
    view = await s.view()
    assert view.last_run == finished
    assert view.timezone == "UTC"


async def test_one_time_schedule_deletes_itself_on_fire() -> None:
    s = Setup()
    await s.set({"schedule": {"date": "2026-10-19T00:00:00Z"}})
    await s.scheduler.fire()
    assert s.schedules.definition is None
    # No credentials are registered, so the scheduled trigger is recorded as a failed run.
    (run,) = s.runs.runs.values()
    assert run.trigger is RunTrigger.SCHEDULED
    assert run.error is not None
    assert run.error.code is RunErrorCode.CREDENTIALS_MISSING


async def test_recurring_fire_keeps_schedule() -> None:
    s = Setup()
    await s.set({"cron": "*/5 * * * *"})
    await s.scheduler.fire()
    assert s.schedules.definition == CronSchedule("*/5 * * * *")


async def test_startup_clears_missed_one_time_without_running() -> None:
    s = Setup(OneTimeSchedule(NOW - timedelta(minutes=1)))
    await s.restore()
    assert s.schedules.definition is None
    assert s.scheduler.job is None
    assert s.runs.runs == {}
    assert s.started == []


async def test_startup_rebuilds_job_from_stored_document() -> None:
    stored = RecurringSchedule("mon", "09:30", "Europe/Madrid")
    s = Setup(stored)
    await s.restore()
    assert s.scheduler.job is not None
    assert s.scheduler.job[0] == stored
    future = OneTimeSchedule(NOW + timedelta(days=1))
    s2 = Setup(future)
    await s2.restore()
    assert s2.scheduler.job is not None
    await Setup().restore()  # nothing stored: nothing to do
