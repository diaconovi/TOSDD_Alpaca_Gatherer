"""The schedule view: times rendered in the schedule's own timezone (FR-013, FR-015).

With no schedule, ``last_run`` is rendered in UTC and the timezone is ``"UTC"``.

>>> from datetime import UTC
>>> view = build_view(None, None, datetime(2026, 10, 8, 6, 20, tzinfo=UTC))
>>> view.timezone, view.last_run.isoformat()
('UTC', '2026-10-08T06:20:00+00:00')
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from alpaca_gatherer.domain.scheduling.definitions import ScheduleDefinition

__all__ = ["ScheduleView", "build_view", "to_display"]


def to_display(value: datetime, timezone: str) -> datetime:
    """The same instant expressed in ``timezone``.

    >>> from datetime import UTC
    >>> to_display(datetime(2026, 11, 2, 23, tzinfo=UTC), "America/New_York").isoformat()
    '2026-11-02T18:00:00-05:00'
    """
    return value.astimezone(ZoneInfo(timezone))


@dataclass(frozen=True, slots=True)
class ScheduleView:
    """Current schedule, next run, last completed run and the timezone they are shown in."""

    schedule: ScheduleDefinition | None
    next_run: datetime | None
    last_run: datetime | None
    timezone: str


def build_view(
    definition: ScheduleDefinition | None, next_run: datetime | None, last_run: datetime | None
) -> ScheduleView:
    """Assemble the view, converting every instant to the display timezone."""
    timezone = definition.timezone if definition is not None else "UTC"
    return ScheduleView(
        schedule=definition,
        next_run=to_display(next_run, timezone) if next_run else None,
        last_run=to_display(last_run, timezone) if last_run else None,
        timezone=timezone,
    )
