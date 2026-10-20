"""APScheduler adapter: next fire times for a frozen "now", one job, job options."""

from datetime import UTC, datetime

import pytest

from alpaca_gatherer.domain.scheduling.definitions import (
    CronSchedule,
    OneTimeSchedule,
    RecurringSchedule,
)
from alpaca_gatherer.infrastructure.scheduler.apscheduler_adapter import ApschedulerJobScheduler

NOW = datetime(2026, 10, 18, 12, 2, 30, tzinfo=UTC)  # a Sunday


async def noop() -> None:
    return None


@pytest.fixture
def scheduler() -> ApschedulerJobScheduler:
    return ApschedulerJobScheduler()


@pytest.mark.parametrize(
    ("definition", "expected"),
    [
        (CronSchedule("*/5 * * * *"), datetime(2026, 10, 18, 12, 5, tzinfo=UTC)),
        # Standard cron: 1-5 is Monday to Friday, 0 is Sunday.
        (CronSchedule("0 18 * * 1-5", "America/New_York"), datetime(2026, 10, 19, 22, tzinfo=UTC)),
        (CronSchedule("30 6 * * 0"), datetime(2026, 10, 25, 6, 30, tzinfo=UTC)),
        (
            RecurringSchedule("mon-fri", "18:00", "America/New_York"),
            datetime(2026, 10, 19, 22, tzinfo=UTC),
        ),
        (RecurringSchedule("sun", "13:00", "UTC"), datetime(2026, 10, 18, 13, tzinfo=UTC)),
        (
            OneTimeSchedule(datetime(2026, 12, 1, 19, 48, 19, tzinfo=UTC), "Asia/Tokyo"),
            datetime(2026, 12, 1, 19, 48, 19, tzinfo=UTC),
        ),
    ],
)
def test_next_fire_time(
    scheduler: ApschedulerJobScheduler,
    definition: CronSchedule | RecurringSchedule | OneTimeSchedule,
    expected: datetime,
) -> None:
    assert scheduler.next_fire_time(definition, NOW) == expected


def test_recurring_across_dst_change(scheduler: ApschedulerJobScheduler) -> None:
    schedule = RecurringSchedule("mon-fri", "18:00", "America/New_York")
    friday = datetime(2026, 10, 30, 12, tzinfo=UTC)
    monday = datetime(2026, 11, 2, 12, tzinfo=UTC)
    assert scheduler.next_fire_time(schedule, friday) == datetime(2026, 10, 30, 22, tzinfo=UTC)
    assert scheduler.next_fire_time(schedule, monday) == datetime(2026, 11, 2, 23, tzinfo=UTC)


def test_past_one_time_never_fires(scheduler: ApschedulerJobScheduler) -> None:
    past = OneTimeSchedule(datetime(2026, 1, 1, tzinfo=UTC))
    assert scheduler.next_fire_time(past, NOW) is None


@pytest.mark.parametrize("expression", ["61 * * * *", "* * *", "* * * * 8", "* * * * fri-mon"])
def test_invalid_cron(scheduler: ApschedulerJobScheduler, expression: str) -> None:
    with pytest.raises(ValueError, match=r".+"):
        scheduler.validate_cron(expression)


async def test_replace_keeps_one_job_with_options(scheduler: ApschedulerJobScheduler) -> None:
    scheduler.start()
    try:
        scheduler.replace_job(CronSchedule("*/5 * * * *"), noop)
        scheduler.replace_job(RecurringSchedule("mon", "10:00"), noop)
        assert scheduler.job_count() == 1
        assert scheduler.job_options() == {
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 60,
        }
        scheduler.remove_job()
        assert scheduler.job_count() == 0
        assert scheduler.job_options() is None
        scheduler.remove_job()  # removing nothing is fine
    finally:
        scheduler.shutdown()
        scheduler.shutdown()
