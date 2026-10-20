"""Schedule definitions and the validation of a schedule request.

Three formats exist: a 5-field cron expression, a recurring ``day`` + ``time``, or a single future
``date``. Each carries an IANA timezone (``UTC`` when the request omits it).

>>> now = datetime(2026, 10, 18, tzinfo=UTC)
>>> parse_schedule_request({"schedule": {"day": "MON-fri", "time": "18:00"}}, now, _NoCron())
RecurringSchedule(day='mon-fri', time='18:00', timezone='UTC')
>>> parse_schedule_request({"schedule": None}, now, _NoCron()) is None
True
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alpaca_gatherer.domain.errors import ScheduleValidationError

__all__ = [
    "WEEKDAYS",
    "CronSchedule",
    "CronValidator",
    "OneTimeSchedule",
    "RecurringSchedule",
    "ScheduleDefinition",
    "parse_day_spec",
    "parse_schedule_request",
    "resolve_timezone",
]

WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
_TOP_LEVEL_FIELDS = frozenset({"cron", "schedule", "timezone"})
_SCHEDULE_FIELDS = frozenset({"day", "time", "date"})


class CronValidator(Protocol):
    """Checks a 5-field cron expression; raises ``ValueError`` with a message when invalid."""

    def validate_cron(self, expression: str) -> None:
        """Raise ``ValueError`` if ``expression`` is not a valid 5-field cron expression."""
        ...


@dataclass(frozen=True, slots=True)
class CronSchedule:
    """A standard 5-field cron expression, evaluated in ``timezone``."""

    cron: str
    timezone: str = "UTC"


@dataclass(frozen=True, slots=True)
class RecurringSchedule:
    """A recurring day/time schedule (``day`` like ``mon-fri``, ``time`` as ``HH:MM``)."""

    day: str
    time: str
    timezone: str = "UTC"

    @property
    def hour(self) -> int:
        """Hour part of ``time``."""
        return int(self.time[:2])

    @property
    def minute(self) -> int:
        """Minute part of ``time``."""
        return int(self.time[3:])


@dataclass(frozen=True, slots=True)
class OneTimeSchedule:
    """A single run at ``date`` (stored in UTC); ``timezone`` only controls how it is shown."""

    date: datetime
    timezone: str = "UTC"


type ScheduleDefinition = CronSchedule | RecurringSchedule | OneTimeSchedule


class _NoCron:
    """Validator used in the module doctest; accepts every expression."""

    def validate_cron(self, expression: str) -> None:
        return None


def resolve_timezone(name: object, field: str = "timezone") -> str:
    """Return ``name`` if it is a valid IANA timezone, else raise ``ScheduleValidationError``.

    >>> resolve_timezone("America/New_York")
    'America/New_York'
    """
    if not isinstance(name, str) or not name.strip():
        raise ScheduleValidationError(field, "must be a non-empty IANA timezone name")
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ScheduleValidationError(field, f"unknown timezone {name!r}") from exc
    return name


def parse_day_spec(value: object, field: str = "schedule.day") -> str:
    """Validate and normalize a day spec: a weekday, an ascending range, or a comma list.

    >>> parse_day_spec("Mon-Fri,sun")
    'mon-fri,sun'
    """
    if not isinstance(value, str) or not value.strip():
        raise ScheduleValidationError(field, "must be a weekday (mon…sun), a range or a list")
    parts = [p.strip() for p in value.strip().lower().split(",")]
    for part in parts:
        if not part:
            raise ScheduleValidationError(field, f"empty item in {value!r}")
        bounds = [b.strip() for b in part.split("-")]
        if len(bounds) > 2 or any(b not in WEEKDAYS for b in bounds):
            raise ScheduleValidationError(
                field, f"{part!r} is not a weekday (mon…sun) or a range of weekdays"
            )
        if len(bounds) == 2 and WEEKDAYS.index(bounds[0]) >= WEEKDAYS.index(bounds[1]):
            raise ScheduleValidationError(field, f"range {part!r} must be ascending (e.g. mon-fri)")
    return ",".join("-".join(b.strip() for b in p.split("-")) for p in parts)


def _parse_time(value: object) -> str:
    if not isinstance(value, str) or not _TIME_RE.match(value):
        raise ScheduleValidationError("schedule.time", "must be HH:MM between 00:00 and 23:59")
    return value


def _parse_date(value: object, now: datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ScheduleValidationError("schedule.date", "must be an ISO 8601 timestamp") from exc
    else:
        raise ScheduleValidationError("schedule.date", "must be an ISO 8601 timestamp")
    if parsed.tzinfo is None:
        raise ScheduleValidationError(
            "schedule.date", "must include a UTC offset (e.g. 2026-12-01T19:48:19Z)"
        )
    if parsed <= now:
        raise ScheduleValidationError("schedule.date", "must be in the future")
    return parsed.astimezone(UTC)


def parse_schedule_request(
    payload: Mapping[str, object], now: datetime, cron_validator: CronValidator
) -> ScheduleDefinition | None:
    """Validate a schedule request and return its definition, or ``None`` to clear the schedule.

    Raises ``ScheduleValidationError`` naming the offending field. Exactly one of ``cron`` or
    ``schedule`` must be present; ``schedule: null`` clears the schedule.
    """
    for key in payload:
        if key not in _TOP_LEVEL_FIELDS:
            raise ScheduleValidationError(key, "unknown field")
    timezone = resolve_timezone(payload["timezone"]) if "timezone" in payload else "UTC"
    has_cron = payload.get("cron") is not None
    has_schedule = "schedule" in payload
    if has_cron and has_schedule:
        raise ScheduleValidationError("schedule", "give exactly one of cron or schedule, not both")
    if not has_cron and not has_schedule:
        raise ScheduleValidationError("schedule", "give exactly one of cron or schedule")

    if has_cron:
        expression = payload["cron"]
        if not isinstance(expression, str) or not expression.strip():
            raise ScheduleValidationError("cron", "must be a 5-field cron expression")
        expression = " ".join(expression.split())
        try:
            cron_validator.validate_cron(expression)
        except ValueError as exc:
            raise ScheduleValidationError("cron", f"invalid cron expression: {exc}") from exc
        return CronSchedule(expression, timezone)

    schedule = payload["schedule"]
    if schedule is None:
        return None
    if not isinstance(schedule, Mapping):
        raise ScheduleValidationError("schedule", "must be an object or null")
    for key in schedule:
        if key not in _SCHEDULE_FIELDS:
            raise ScheduleValidationError(f"schedule.{key}", "unknown field")
    if "date" in schedule:
        if "day" in schedule or "time" in schedule:
            raise ScheduleValidationError("schedule", "give either date, or day and time")
        return OneTimeSchedule(_parse_date(schedule["date"], now), timezone)
    if "day" not in schedule:
        raise ScheduleValidationError("schedule.day", "is required with time")
    if "time" not in schedule:
        raise ScheduleValidationError("schedule.time", "is required with day")
    return RecurringSchedule(
        parse_day_spec(schedule["day"]), _parse_time(schedule["time"]), timezone
    )
