"""``/api/v1/runs`` end to end with fake gateways and a real MongoDB."""

import asyncio
import time
from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from alpaca_gatherer.domain.errors import CollectorUnavailable
from alpaca_gatherer.main import Overrides
from tests.conftest import AppFactory
from tests.fakes import FrozenClock
from tests.world import World, build_world

CREDENTIALS = {"api_key": "PKRUNSAPIKEY0001", "api_secret": "runs-api-secret-0002"}
RUN_FIELDS = {
    "run_id",
    "trigger",
    "status",
    "started_at",
    "finished_at",
    "price_window_end",
    "counts",
    "error",
}


@pytest.fixture
def world() -> World:
    # The test thresholds use 5 sessions; they must lie inside the calendar range of the clock.
    return build_world(5, start=date(2026, 10, 5))


@pytest.fixture
def overrides(world: World, clock: FrozenClock) -> Overrides:
    return Overrides(clock=clock, collector=world.collector, alpaca=world.alpaca)


async def finished(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        body: dict[str, Any] = (await client.get(f"/api/v1/runs/{run_id}")).json()
        if body["status"] != "running":
            return body
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish")


async def test_run_without_credentials_is_409(
    app_factory: AppFactory, overrides: Overrides
) -> None:
    async with app_factory(overrides) as (_, client):
        response = await client.post("/api/v1/runs")
    assert response.status_code == 409
    assert response.json()["type"] == "urn:alpaca-gatherer:problem:credentials_missing"


async def test_run_succeeds_and_feeds_lookups(
    app_factory: AppFactory, overrides: Overrides
) -> None:
    async with app_factory(overrides) as (_, client):
        await client.post("/api/v1/credentials", json=CREDENTIALS)
        accepted = await client.post("/api/v1/runs")
        assert accepted.status_code == 202
        body = accepted.json()
        assert set(body) == {"run_id", "status", "started_at"}
        assert body["status"] == "running"
        assert accepted.headers["location"] == f"/api/v1/runs/{body['run_id']}"

        run = await finished(client, body["run_id"])
        assert set(run) == RUN_FIELDS
        assert run["status"] == "succeeded", run["error"]
        assert run["trigger"] == "manual"
        assert run["price_window_end"] == run["started_at"] == body["started_at"]
        assert run["counts"] == {
            "matched": 3,
            "ambiguous": 0,
            "unmatched": 0,
            "total": 3,
            "by_reason": {},
        }
        by_epic = (await client.get("/api/v1/mappings", params={"capital_epic": "BRKB"})).json()
        by_symbol = (await client.get("/api/v1/mappings", params={"alpaca_symbol": "BRK.B"})).json()
    assert by_epic["alpaca_symbol"] == "BRK.B"
    assert by_symbol["capital_epic"] == "BRKB"
    assert by_epic["run_id"] == run["run_id"]


async def test_second_run_while_running_is_409(
    app_factory: AppFactory, overrides: Overrides, world: World
) -> None:
    gate = asyncio.Event()
    world.collector.gate = gate
    async with app_factory(overrides) as (_, client):
        await client.post("/api/v1/credentials", json=CREDENTIALS)
        first = (await client.post("/api/v1/runs")).json()
        second = await client.post("/api/v1/runs")
        gate.set()
        await finished(client, first["run_id"])
    assert second.status_code == 409
    problem = second.json()
    assert problem["type"] == "urn:alpaca-gatherer:problem:run_in_progress"
    assert problem["active_run_id"] == first["run_id"]


async def test_unknown_run_is_404(app_factory: AppFactory, overrides: Overrides) -> None:
    async with app_factory(overrides) as (_, client):
        response = await client.get("/api/v1/runs/00000000-0000-4000-8000-000000000000")
    assert response.status_code == 404
    assert response.json()["type"] == "urn:alpaca-gatherer:problem:run_not_found"


async def test_list_runs_newest_first_and_validation(
    app_factory: AppFactory, overrides: Overrides, clock: FrozenClock
) -> None:
    async with app_factory(overrides) as (_, client):
        await client.post("/api/v1/credentials", json=CREDENTIALS)
        ids = []
        for _ in range(3):
            run_id = (await client.post("/api/v1/runs")).json()["run_id"]
            await finished(client, run_id)
            ids.append(run_id)
            clock.advance(timedelta(minutes=1))
        page = (await client.get("/api/v1/runs", params={"limit": 2, "offset": 0})).json()
        default = (await client.get("/api/v1/runs")).json()
        bad = [
            await client.get("/api/v1/runs", params=params)
            for params in ({"limit": 0}, {"limit": 51}, {"offset": -1}, {"limit": "x"})
        ]
    assert [r["run_id"] for r in page["items"]] == [ids[2], ids[1]]
    assert (page["limit"], page["offset"], page["total"]) == (2, 0, 3)
    assert default["limit"] == 20
    assert len(default["items"]) == 3
    for response in bad:
        assert response.status_code == 422
        assert response.json()["type"] == "urn:alpaca-gatherer:problem:validation_error"


async def test_failed_run_keeps_previous_lookups(
    app_factory: AppFactory, overrides: Overrides, world: World, clock: FrozenClock
) -> None:
    async with app_factory(overrides) as (_, client):
        await client.post("/api/v1/credentials", json=CREDENTIALS)
        good = (await client.post("/api/v1/runs")).json()["run_id"]
        await finished(client, good)
        before = {
            epic: (await client.get("/api/v1/mappings", params={"capital_epic": epic})).json()
            for epic in ("TSLA", "BRKB", "CARR")
        }
        world.collector.fail_with = CollectorUnavailable(
            "prices TSLA: the collector could not be reached"
        )
        clock.advance(timedelta(minutes=5))
        bad = (await client.post("/api/v1/runs")).json()["run_id"]
        failed = await finished(client, bad)
        after = {
            epic: (await client.get("/api/v1/mappings", params={"capital_epic": epic})).json()
            for epic in ("TSLA", "BRKB", "CARR")
        }
    assert failed["status"] == "failed"
    assert failed["error"]["code"] == "collector_unavailable"
    assert after == before


async def test_post_returns_quickly_while_collector_is_slow(
    app_factory: AppFactory, overrides: Overrides, world: World
) -> None:
    world.collector.delay = 5.0
    async with app_factory(overrides) as (_, client):
        await client.post("/api/v1/credentials", json=CREDENTIALS)
        started = time.perf_counter()
        response = await client.post("/api/v1/runs")
        elapsed = time.perf_counter() - started
    assert response.status_code == 202
    assert elapsed < 1.0
