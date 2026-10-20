"""``/api/v1/schedules/current`` end to end against a real MongoDB and the real scheduler."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest

from alpaca_gatherer.config import Settings
from alpaca_gatherer.domain.runs import Run, RunCounts, RunTrigger, RunWindow
from alpaca_gatherer.infrastructure.db.client import Collections, MongoDatabase
from alpaca_gatherer.infrastructure.db.run_repo import MongoRunRepository
from tests.conftest import AppFactory
from tests.fakes import FrozenClock

URL = "/api/v1/schedules/current"


@pytest.mark.parametrize(
    ("body", "schedule", "next_run", "timezone"),
    [
        ({"cron": "*/5 * * * *"}, {"cron": "*/5 * * * *"}, "2026-10-18T12:05:00Z", "UTC"),
        (
            {"schedule": {"day": "mon-fri", "time": "18:00"}, "timezone": "America/New_York"},
            {"schedule": {"day": "mon-fri", "time": "18:00"}},
            "2026-10-19T18:00:00-04:00",
            "America/New_York",
        ),
        (
            {"schedule": {"date": "2026-12-01T19:48:19Z"}},
            {"schedule": {"date": "2026-12-01T19:48:19Z"}},
            "2026-12-01T19:48:19Z",
            "UTC",
        ),
        (
            {"schedule": {"date": "2026-12-01T19:48:19Z"}, "timezone": "Asia/Tokyo"},
            {"schedule": {"date": "2026-12-02T04:48:19+09:00"}},
            "2026-12-02T04:48:19+09:00",
            "Asia/Tokyo",
        ),
    ],
)
async def test_put_each_format(
    app_factory: AppFactory,
    body: dict[str, Any],
    schedule: dict[str, Any],
    next_run: str,
    timezone: str,
) -> None:
    async with app_factory() as (_, client):
        put = await client.put(URL, json=body)
        get = await client.get(URL)
    assert put.status_code == 200, put.text
    view = put.json()
    assert view == {
        "schedule": schedule,
        "next_run": next_run,
        "last_run": None,
        "timezone": timezone,
    }
    assert get.json() == view


@pytest.mark.parametrize(
    ("body", "loc"),
    [
        (
            {"cron": "*/5 * * * *", "schedule": {"day": "mon", "time": "10:00"}},
            ["body", "schedule"],
        ),
        ({"cron": "61 * * * *"}, ["body", "cron"]),
        ({"schedule": {"day": "mon-xyz", "time": "10:00"}}, ["body", "schedule", "day"]),
        ({"schedule": {"day": "mon", "time": "25:00"}}, ["body", "schedule", "time"]),
        ({"schedule": {"date": "2026-01-01T00:00:00Z"}}, ["body", "schedule", "date"]),
        ({"cron": "*/5 * * * *", "timezone": "Mars/Base"}, ["body", "timezone"]),
        ({"cron": "*/5 * * * *", "every": 1}, ["body", "every"]),
        ({"schedule": {"day": "mon", "time": "10:00", "x": 1}}, ["body", "schedule", "x"]),
        ({}, ["body", "schedule"]),
    ],
)
async def test_invalid_requests_leave_schedule_unchanged(
    app_factory: AppFactory, body: dict[str, Any], loc: list[str]
) -> None:
    async with app_factory() as (_, client):
        await client.put(URL, json={"cron": "0 * * * *"})
        before = (await client.get(URL)).json()
        response = await client.put(URL, json=body)
        after = (await client.get(URL)).json()
    assert response.status_code == 422
    problem = response.json()
    assert problem["type"] == "urn:alpaca-gatherer:problem:validation_error"
    assert problem["errors"][0]["loc"] == loc
    assert after == before


async def test_null_clears_schedule(app_factory: AppFactory) -> None:
    async with app_factory() as (_, client):
        await client.put(URL, json={"cron": "0 * * * *"})
        cleared = await client.put(URL, json={"schedule": None})
    assert cleared.status_code == 200
    assert cleared.json() == {
        "schedule": None,
        "next_run": None,
        "last_run": None,
        "timezone": "UTC",
    }


async def test_schedule_and_last_run_survive_restart(
    app_factory: AppFactory,
    make_settings: Callable[..., Settings],
    db: MongoDatabase,
    collections: Collections,
    clock: FrozenClock,
) -> None:
    settings = make_settings()
    body = {"schedule": {"day": "mon-fri", "time": "18:00"}, "timezone": "America/New_York"}
    async with app_factory(settings=settings) as (_, client):
        await client.put(URL, json=body)
        run = Run.start("r-last", RunTrigger.MANUAL, clock.now() - timedelta(hours=2), {})
        done = run.succeed(
            clock.now() - timedelta(hours=1),
            RunCounts(1, 0, 0),
            RunWindow(clock.now(), clock.now(), 5),
        )
        await MongoRunRepository(db, collections).insert_terminal(done)
        before = (await client.get(URL)).json()
    clock.advance(timedelta(days=2))  # restart two days later: next_run is recomputed from now
    async with app_factory(settings=settings) as (_, client):
        after = (await client.get(URL)).json()
    assert before["last_run"] == "2026-10-18T07:00:00-04:00"
    assert after["schedule"] == before["schedule"]
    assert after["timezone"] == before["timezone"] == "America/New_York"
    assert after["last_run"] == before["last_run"]
    assert before["next_run"] == "2026-10-19T18:00:00-04:00"
    assert after["next_run"] == "2026-10-20T18:00:00-04:00"


async def test_missed_one_time_schedule_is_cleared_at_startup(
    app_factory: AppFactory, make_settings: Callable[..., Settings], clock: FrozenClock
) -> None:
    settings = make_settings()
    async with app_factory(settings=settings) as (_, client):
        await client.put(URL, json={"schedule": {"date": "2026-10-18T13:00:00Z"}})
    clock.advance(timedelta(hours=2))
    async with app_factory(settings=settings) as (_, client):
        view = (await client.get(URL)).json()
    assert view["schedule"] is None
    assert view["next_run"] is None
