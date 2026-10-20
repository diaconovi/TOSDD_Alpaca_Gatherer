"""Request and response models of ``/api/v1/schedules/current``."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from alpaca_gatherer.domain.scheduling.definitions import (
    CronSchedule,
    OneTimeSchedule,
    RecurringSchedule,
)
from alpaca_gatherer.domain.scheduling.rendering import ScheduleView, to_display

__all__ = [
    "CronDefinition",
    "OneTimeBody",
    "RecurringBody",
    "ScheduleBodyRequest",
    "ScheduleDefinitionBody",
    "ScheduleRequest",
    "ScheduleViewResponse",
]


class ScheduleBodyRequest(BaseModel):
    """The ``schedule`` object: either ``day`` + ``time`` or a single ``date``."""

    model_config = ConfigDict(extra="forbid")

    day: str | None = Field(default=None, examples=["mon-fri"])
    time: str | None = Field(default=None, examples=["18:00"])
    date: str | None = Field(default=None, examples=["2026-12-01T19:48:19Z"])


class ScheduleRequest(BaseModel):
    """Exactly one of ``cron`` or ``schedule``; ``schedule: null`` removes the schedule.

    ``timezone`` is an optional IANA name (default UTC). The cross-field rules are checked by the
    domain, which names the offending field in a 422.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"cron": "*/5 * * * *"},
                {"schedule": {"day": "mon-fri", "time": "18:00"}, "timezone": "America/New_York"},
                {"schedule": {"date": "2026-12-01T19:48:19Z"}},
                {"schedule": None},
            ]
        },
    )

    cron: str | None = None
    schedule: ScheduleBodyRequest | None = None
    timezone: str | None = Field(default=None, description="IANA timezone, default UTC")


class CronDefinition(BaseModel):
    """A cron schedule."""

    cron: str


class RecurringBody(BaseModel):
    """A recurring day/time schedule."""

    day: str
    time: str


class OneTimeBody(BaseModel):
    """A one-time schedule."""

    date: datetime


class ScheduleDefinitionBody(BaseModel):
    """A ``schedule`` object (recurring or one-time)."""

    schedule: RecurringBody | OneTimeBody


class ScheduleViewResponse(BaseModel):
    """The schedule, next run, last completed run and the timezone they are shown in."""

    schedule: CronDefinition | ScheduleDefinitionBody | None
    next_run: datetime | None
    last_run: datetime | None
    timezone: str

    @classmethod
    def of(cls, view: ScheduleView) -> ScheduleViewResponse:
        """Build from the domain view."""
        schedule: CronDefinition | ScheduleDefinitionBody | None
        match view.schedule:
            case CronSchedule(cron=cron):
                schedule = CronDefinition(cron=cron)
            case RecurringSchedule(day=day, time=time):
                schedule = ScheduleDefinitionBody(schedule=RecurringBody(day=day, time=time))
            case OneTimeSchedule(date=date):
                schedule = ScheduleDefinitionBody(
                    schedule=OneTimeBody(date=to_display(date, view.timezone))
                )
            case None:
                schedule = None
        return cls(
            schedule=schedule,
            next_run=view.next_run,
            last_run=view.last_run,
            timezone=view.timezone,
        )
