"""APScheduler 3 adapter: the single ``matching-run`` job (research R7).

The job is only a cache of the persisted schedule; it is rebuilt from MongoDB at startup and on
every schedule change. APScheduler 3 numbers cron weekdays from Monday = 0, unlike standard cron
(Sunday = 0), so the day-of-week field is translated to weekday names first.

>>> translate_day_of_week("1-5")
'mon,tue,wed,thu,fri'
>>> translate_day_of_week("0,6/2")
'sat,sun'
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from alpaca_gatherer.application.ports import JobCallback
from alpaca_gatherer.domain.scheduling.definitions import (
    CronSchedule,
    OneTimeSchedule,
    RecurringSchedule,
    ScheduleDefinition,
)

__all__ = ["JOB_ID", "ApschedulerJobScheduler", "translate_day_of_week"]

log = logging.getLogger(__name__)

JOB_ID = "matching-run"
JOB_OPTIONS: dict[str, Any] = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 60}
_CRON_DAYS = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


def _day_number(token: str) -> int:
    token = token.strip().lower()
    if token in _CRON_DAYS:
        return _CRON_DAYS.index(token)
    value = int(token)
    if not 0 <= value <= 7:
        raise ValueError(f"day of week {value} is out of range (0-7)")
    return value


def translate_day_of_week(field: str) -> str:
    """Standard cron day-of-week (0 or 7 = Sunday, names allowed) as explicit weekday names.

    Raises ``ValueError`` for an invalid field.
    """
    if field == "*":
        return field
    days: list[int] = []
    for part in field.split(","):
        base, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if step < 1:
            raise ValueError(f"invalid step in {part!r}")
        if base == "*":
            low, high = 0, 6
        elif "-" in base:
            first, last = base.split("-", 1)
            low, high = _day_number(first), _day_number(last)
            if low > high:
                raise ValueError(f"invalid range {base!r}")
        else:
            low = high = _day_number(base)
            if step_text:
                high = 6
        days += [d % 7 for d in range(low, high + 1, step)]
    unique = sorted(set(days), key=lambda d: (d + 6) % 7)  # Monday first, like APScheduler
    return ",".join(_CRON_DAYS[d] for d in unique)


def _cron_trigger(expression: str, timezone: str) -> CronTrigger:
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError(f"expected 5 fields, got {len(fields)}")
    minute, hour, day, month, day_of_week = fields
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=translate_day_of_week(day_of_week),
        timezone=ZoneInfo(timezone),
    )


def build_trigger(definition: ScheduleDefinition) -> CronTrigger | DateTrigger:
    """The APScheduler trigger for a schedule definition."""
    tz = ZoneInfo(definition.timezone)
    match definition:
        case CronSchedule(cron=expression):
            return _cron_trigger(expression, definition.timezone)
        case RecurringSchedule():
            return CronTrigger(
                day_of_week=definition.day,
                hour=definition.hour,
                minute=definition.minute,
                timezone=tz,
            )
        case OneTimeSchedule(date=when):
            return DateTrigger(run_date=when, timezone=tz)


class ApschedulerJobScheduler:
    """Implements ``JobScheduler`` and ``CronValidator`` with ``AsyncIOScheduler``."""

    def __init__(self, scheduler: AsyncIOScheduler | None = None) -> None:
        self._scheduler = scheduler or AsyncIOScheduler(timezone=UTC)

    def validate_cron(self, expression: str) -> None:
        """Raise ``ValueError`` if ``expression`` is not a valid 5-field cron expression."""
        _cron_trigger(expression, "UTC")

    def replace_job(self, definition: ScheduleDefinition, callback: JobCallback) -> None:
        """Create or replace the single matching job."""
        self._scheduler.add_job(
            callback,
            trigger=build_trigger(definition),
            id=JOB_ID,
            name="scheduled matching run",
            replace_existing=True,
            **JOB_OPTIONS,
        )
        log.info("scheduled job set: %s", definition)

    def remove_job(self) -> None:
        """Remove the matching job if there is one."""
        try:
            self._scheduler.remove_job(JOB_ID)
        except JobLookupError:
            return
        log.info("scheduled job removed")

    def next_fire_time(self, definition: ScheduleDefinition, now: datetime) -> datetime | None:
        """When ``definition`` next fires after ``now`` (UTC), or ``None`` if never."""
        if isinstance(definition, OneTimeSchedule):
            # A DateTrigger reports its date even when it lies in the past.
            return definition.date if definition.date > now else None
        # APScheduler includes "now" itself; the next run is strictly after it.
        after = now + timedelta(microseconds=1)
        fire: datetime | None = build_trigger(definition).get_next_fire_time(None, after)
        return fire.astimezone(UTC) if fire else None

    def job_options(self) -> dict[str, Any] | None:
        """Options of the current job (for inspection and tests)."""
        job = self._scheduler.get_job(JOB_ID)
        if job is None:
            return None
        return {
            "coalesce": job.coalesce,
            "max_instances": job.max_instances,
            "misfire_grace_time": job.misfire_grace_time,
        }

    def job_count(self) -> int:
        """Number of scheduled jobs."""
        return len(self._scheduler.get_jobs())

    def start(self) -> None:
        """Start firing jobs (needs a running event loop)."""
        if not self._scheduler.running:
            self._scheduler.start()

    def shutdown(self) -> None:
        """Stop firing jobs without waiting for running ones."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
