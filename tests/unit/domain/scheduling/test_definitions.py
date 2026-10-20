"""Schedule request parsing and validation (research R7)."""

from datetime import UTC, datetime

import pytest

from alpaca_gatherer.domain.errors import ScheduleValidationError
from alpaca_gatherer.domain.scheduling.definitions import (
    CronSchedule,
    OneTimeSchedule,
    RecurringSchedule,
    parse_day_spec,
    parse_schedule_request,
)

NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)


class StrictCron:
    """Accepts 5 fields whose minute is 0-59 or ``*``-based (enough for these tests)."""

    def validate_cron(self, expression: str) -> None:
        fields = expression.split()
        if len(fields) != 5:
            raise ValueError("expected 5 fields")
        if fields[0].isdigit() and int(fields[0]) > 59:
            raise ValueError(f"minute {fields[0]} is out of range")


def parse(payload: dict[str, object]) -> object:
    return parse_schedule_request(payload, NOW, StrictCron())


def field_of(payload: dict[str, object]) -> str:
    with pytest.raises(ScheduleValidationError) as info:
        parse(payload)
    return info.value.field


def test_cron_defaults_to_utc() -> None:
    assert parse({"cron": "*/5 * * * *"}) == CronSchedule("*/5 * * * *", "UTC")
    assert parse({"cron": " 0  18 * * 1-5 ", "timezone": "Europe/Madrid"}) == CronSchedule(
        "0 18 * * 1-5", "Europe/Madrid"
    )


def test_recurring_is_normalized() -> None:
    assert parse(
        {"schedule": {"day": "MON-Fri", "time": "18:00"}, "timezone": "America/New_York"}
    ) == RecurringSchedule("mon-fri", "18:00", "America/New_York")


def test_one_time_keeps_instant_in_utc() -> None:
    parsed = parse({"schedule": {"date": "2026-12-01T14:48:19-05:00"}, "timezone": "Asia/Tokyo"})
    assert parsed == OneTimeSchedule(datetime(2026, 12, 1, 19, 48, 19, tzinfo=UTC), "Asia/Tokyo")
    assert parse({"schedule": {"date": "2026-12-01T19:48:19Z"}}) == OneTimeSchedule(
        datetime(2026, 12, 1, 19, 48, 19, tzinfo=UTC), "UTC"
    )


def test_null_schedule_clears() -> None:
    assert parse({"schedule": None}) is None
    assert parse({"schedule": None, "timezone": "UTC"}) is None


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"cron": "*/5 * * * *", "schedule": {"day": "mon", "time": "10:00"}}, "schedule"),
        ({"cron": "*/5 * * * *", "schedule": None}, "schedule"),
        ({}, "schedule"),
        ({"timezone": "UTC"}, "schedule"),
        ({"schedule": {"date": "2026-12-01T00:00:00Z", "day": "mon"}}, "schedule"),
        ({"schedule": {"date": "2026-12-01T00:00:00Z", "time": "10:00"}}, "schedule"),
        ({"schedule": {"day": "mon"}}, "schedule.time"),
        ({"schedule": {"time": "10:00"}}, "schedule.day"),
        ({"schedule": {"day": "mon-xyz", "time": "10:00"}}, "schedule.day"),
        ({"schedule": {"day": "fri-mon", "time": "10:00"}}, "schedule.day"),
        ({"schedule": {"day": "mon-mon", "time": "10:00"}}, "schedule.day"),
        ({"schedule": {"day": "", "time": "10:00"}}, "schedule.day"),
        ({"schedule": {"day": "mon,,tue", "time": "10:00"}}, "schedule.day"),
        ({"schedule": {"day": "mon-tue-wed", "time": "10:00"}}, "schedule.day"),
        ({"schedule": {"day": 3, "time": "10:00"}}, "schedule.day"),
        ({"schedule": {"day": "mon", "time": "25:00"}}, "schedule.time"),
        ({"schedule": {"day": "mon", "time": "7:5"}}, "schedule.time"),
        ({"schedule": {"day": "mon", "time": "12:60"}}, "schedule.time"),
        ({"schedule": {"date": "2026-10-01T00:00:00Z"}}, "schedule.date"),
        ({"schedule": {"date": "2026-12-01T00:00:00"}}, "schedule.date"),
        ({"schedule": {"date": "tomorrow"}}, "schedule.date"),
        ({"schedule": {"date": 12345}}, "schedule.date"),
        ({"schedule": {"date": "2026-12-01T00:00:00Z"}, "timezone": "Mars/Base"}, "timezone"),
        ({"cron": "*/5 * * * *", "timezone": ""}, "timezone"),
        ({"cron": "61 * * * *"}, "cron"),
        ({"cron": "* * *"}, "cron"),
        ({"cron": "   "}, "cron"),
        ({"cron": 5}, "cron"),
        ({"schedule": "daily"}, "schedule"),
        ({"schedule": {"every": "day"}}, "schedule.every"),
        ({"cron": "* * * * *", "extra": 1}, "extra"),
    ],
)
def test_invalid_requests_name_the_field(payload: dict[str, object], field: str) -> None:
    assert field_of(payload) == field


def test_day_spec_lists_and_ranges() -> None:
    assert parse_day_spec("sun") == "sun"
    assert parse_day_spec("mon-wed, fri ,sun") == "mon-wed,fri,sun"
    assert parse_day_spec("mon - fri") == "mon-fri"


def test_recurring_hour_and_minute() -> None:
    schedule = RecurringSchedule("mon", "07:05")
    assert (schedule.hour, schedule.minute) == (7, 5)
