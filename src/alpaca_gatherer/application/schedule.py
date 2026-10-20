"""View, set and clear the schedule; fire scheduled runs; restore the job at startup.

The persisted schedule is the source of truth (FR-019); the in-process job is rebuilt from it.
"""

import logging
from collections.abc import Mapping

from alpaca_gatherer.application.ports import Clock, JobScheduler, RunRepository, ScheduleRepository
from alpaca_gatherer.application.runs.start_run import StartRun
from alpaca_gatherer.domain.runs import RunTrigger
from alpaca_gatherer.domain.scheduling.definitions import OneTimeSchedule, parse_schedule_request
from alpaca_gatherer.domain.scheduling.rendering import ScheduleView, build_view

__all__ = ["GetSchedule", "OnScheduledFire", "RestoreScheduleOnStartup", "SetSchedule"]

log = logging.getLogger(__name__)


class GetSchedule:
    """The schedule, its next run, the last completed run and the display timezone."""

    def __init__(
        self,
        schedules: ScheduleRepository,
        runs: RunRepository,
        scheduler: JobScheduler,
        clock: Clock,
    ) -> None:
        self._schedules = schedules
        self._runs = runs
        self._scheduler = scheduler
        self._clock = clock

    async def __call__(self) -> ScheduleView:
        """Build the schedule view."""
        definition = await self._schedules.get()
        next_run = (
            self._scheduler.next_fire_time(definition, self._clock.now()) if definition else None
        )
        last = await self._runs.latest_succeeded()
        return build_view(definition, next_run, last.finished_at if last else None)


class OnScheduledFire:
    """Job callback: start a scheduled run; a one-time schedule removes itself (FR-020)."""

    def __init__(self, start_run: StartRun, schedules: ScheduleRepository) -> None:
        self._start_run = start_run
        self._schedules = schedules

    async def __call__(self) -> None:
        """Fire once."""
        if isinstance(await self._schedules.get(), OneTimeSchedule):
            await self._schedules.delete()
            log.info("one-time schedule fired and was cleared")
        try:
            run = await self._start_run(RunTrigger.SCHEDULED)
        except Exception:
            log.exception("scheduled run could not be started")
            return
        log.info("scheduled trigger handled as run %s (%s)", run.run_id, run.status)


class SetSchedule:
    """Replace or clear the schedule; invalid input changes nothing."""

    def __init__(
        self,
        schedules: ScheduleRepository,
        scheduler: JobScheduler,
        clock: Clock,
        on_fire: OnScheduledFire,
        view: GetSchedule,
    ) -> None:
        self._schedules = schedules
        self._scheduler = scheduler
        self._clock = clock
        self._on_fire = on_fire
        self._view = view

    async def __call__(self, payload: Mapping[str, object]) -> ScheduleView:
        """Apply a schedule request; raises ``ScheduleValidationError`` naming the field."""
        now = self._clock.now()
        definition = parse_schedule_request(payload, now, self._scheduler)
        if definition is None:
            await self._schedules.delete()
            self._scheduler.remove_job()
            log.info("schedule cleared")
        else:
            await self._schedules.put(definition, now)
            self._scheduler.replace_job(definition, self._on_fire)
            log.info("schedule set: %s", definition)
        return await self._view()


class RestoreScheduleOnStartup:
    """Rebuild the job from the stored schedule; clear a one-time schedule that was missed."""

    def __init__(
        self,
        schedules: ScheduleRepository,
        scheduler: JobScheduler,
        clock: Clock,
        on_fire: OnScheduledFire,
    ) -> None:
        self._schedules = schedules
        self._scheduler = scheduler
        self._clock = clock
        self._on_fire = on_fire

    async def __call__(self) -> None:
        """Restore."""
        definition = await self._schedules.get()
        if definition is None:
            return
        if isinstance(definition, OneTimeSchedule) and definition.date <= self._clock.now():
            await self._schedules.delete()
            log.warning(
                "one-time schedule at %s was missed while the service was stopped; cleared",
                definition.date.isoformat(),
            )
            return
        self._scheduler.replace_job(definition, self._on_fire)
        log.info("schedule restored: %s", definition)
