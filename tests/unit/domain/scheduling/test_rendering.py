"""Schedule view rendering in the schedule's timezone, including DST."""

from datetime import UTC, datetime

from alpaca_gatherer.domain.scheduling.definitions import (
    CronSchedule,
    OneTimeSchedule,
    RecurringSchedule,
)
from alpaca_gatherer.domain.scheduling.rendering import build_view, to_display

LAST = datetime(2026, 10, 8, 6, 20, tzinfo=UTC)


def test_times_rendered_in_schedule_timezone() -> None:
    schedule = CronSchedule("0 * * * *", "Asia/Kolkata")
    view = build_view(schedule, datetime(2026, 10, 18, 13, tzinfo=UTC), LAST)
    assert view.timezone == "Asia/Kolkata"
    assert view.next_run is not None
    assert view.next_run.isoformat() == "2026-10-18T18:30:00+05:30"
    assert view.last_run is not None
    assert view.last_run.isoformat() == "2026-10-08T11:50:00+05:30"


def test_no_schedule_renders_last_run_in_utc() -> None:
    view = build_view(None, None, LAST)
    assert view.schedule is None
    assert view.next_run is None
    assert view.timezone == "UTC"
    assert view.last_run is not None
    assert view.last_run.isoformat() == "2026-10-08T06:20:00+00:00"
    assert build_view(None, None, None).last_run is None


def test_recurring_new_york_across_november_dst_change() -> None:
    schedule = RecurringSchedule("mon-fri", "18:00", "America/New_York")
    before = build_view(schedule, datetime(2026, 10, 30, 22, tzinfo=UTC), None)
    after = build_view(schedule, datetime(2026, 11, 2, 23, tzinfo=UTC), None)
    assert before.next_run is not None
    assert after.next_run is not None
    assert before.next_run.isoformat() == "2026-10-30T18:00:00-04:00"
    assert after.next_run.isoformat() == "2026-11-02T18:00:00-05:00"


def test_one_time_keeps_its_instant() -> None:
    instant = datetime(2026, 12, 1, 19, 48, 19, tzinfo=UTC)
    view = build_view(OneTimeSchedule(instant, "Asia/Tokyo"), instant, None)
    assert view.next_run == instant
    assert view.next_run is not None
    assert view.next_run.isoformat() == "2026-12-02T04:48:19+09:00"
    assert to_display(instant, "UTC") == instant
