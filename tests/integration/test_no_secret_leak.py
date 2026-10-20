"""SC-003: the plain Alpaca key and secret never appear in responses, logs or stored documents."""

import asyncio
import logging
import time
from datetime import date, timedelta

import httpx
import pytest

from alpaca_gatherer.domain.errors import AlpacaAuthFailed
from alpaca_gatherer.infrastructure.db.client import Collections, MongoDatabase
from alpaca_gatherer.main import Overrides
from tests.conftest import AppFactory
from tests.fakes import FrozenClock
from tests.world import build_world

KEY = "PKLEAKCHECKKEY7777"
SECRET = "leak-check-secret-value-8888"


async def wait_done(client: httpx.AsyncClient, run_id: str) -> httpx.Response:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = await client.get(f"/api/v1/runs/{run_id}")
        if response.json()["status"] != "running":
            return response
        await asyncio.sleep(0.02)
    raise AssertionError("run did not finish")


async def test_plain_credentials_never_leak(
    app_factory: AppFactory,
    db: MongoDatabase,
    collections: Collections,
    clock: FrozenClock,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    world = build_world(5, start=date(2026, 10, 5))
    overrides = Overrides(clock=clock, collector=world.collector, alpaca=world.alpaca)
    bodies: list[str] = []
    async with app_factory(overrides) as (_, client):
        for response in (
            await client.post("/api/v1/credentials", json={"api_key": KEY, "api_secret": SECRET}),
            await client.post("/api/v1/credentials", json={"api_key": KEY, "api_secret": SECRET}),
            await client.post("/api/v1/credentials", json={"api_key": KEY, "x": SECRET}),
        ):
            bodies.append(response.text)

        world.alpaca.fail_with = AlpacaAuthFailed()
        failing = (await client.post("/api/v1/runs")).json()["run_id"]
        bodies.append((await wait_done(client, failing)).text)

        world.alpaca.fail_with = None
        clock.advance(timedelta(minutes=1))
        succeeding = (await client.post("/api/v1/runs")).json()["run_id"]
        bodies.append((await wait_done(client, succeeding)).text)
        bodies.append((await client.get("/api/v1/runs")).text)
        bodies.append((await client.get("/api/v1/mappings?capital_epic=TSLA")).text)
        bodies.append((await client.get("/api/v1/schedules/current")).text)

    assert world.alpaca.seen_credentials, "the fake Alpaca gateway was never called"
    assert '"status":"succeeded"' in bodies[4]
    stored = []
    for name in await db.list_collection_names():
        if name.startswith(collections.mapping):
            stored += [str(doc) async for doc in db[name].find({})]
    captured = capfd.readouterr()
    haystacks = {
        "responses": "\n".join(bodies),
        "log records": caplog.text,
        "stderr": captured.err + captured.out,
        "mongo": "\n".join(stored),
    }
    for where, text in haystacks.items():
        assert KEY not in text, f"API key found in {where}"
        assert SECRET not in text, f"API secret found in {where}"
