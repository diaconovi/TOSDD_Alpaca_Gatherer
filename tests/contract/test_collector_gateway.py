"""``CollectorGateway`` against the collector's HTTP API (respx intercepts the client's httpx)."""

import asyncio
import json
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
import respx
from tenacity import wait_none
from to_collector_client import CollectorClient

from alpaca_gatherer.domain.errors import CollectorIncompleteData, CollectorUnavailable
from alpaca_gatherer.domain.mapping import Source
from alpaca_gatherer.infrastructure.clients.collector import NO_HISTORY, CollectorGateway

BASE = "http://collector.test:8001"
START = datetime(2026, 9, 10, 13, tzinfo=UTC)
END = datetime(2026, 10, 7, 20, tzinfo=UTC)

REGIONS = [
    {"name": "popular_shares", "description": "Popular shares", "catalog": []},
    {
        "name": "us",
        "description": "US",
        "catalog": [
            {"name": n, "description": n}
            for n in ("most_traded", "top_gainers", "top_losers", "most_volatile")
        ],
    },
    {"name": "gb", "description": "UK", "catalog": [{"name": "most_traded", "description": "x"}]},
]


def market(epic: str, kind: str = "SHARES") -> dict[str, Any]:
    return {
        "instrumentName": f"{epic} Inc",
        "epic": epic,
        "symbol": f"{epic}us" if epic.endswith("US") else epic,
        "instrumentType": kind,
        "marketStatus": "CLOSED",
        "bid": 1.0,
        "offer": 1.1,
    }


def detail(epic: str) -> dict[str, Any]:
    return {
        "instrument": {
            "epic": epic,
            "symbol": epic,
            "name": f"{epic} Inc",
            "type": "SHARES",
            "currency": "USD",
            "openingHours": {"mon": ["13:30 - 20:00"], "sat": [], "zone": "UTC"},
        },
        "dealingRules": {},
        "snapshot": {},
    }


def price(ts: str, bid: float | None, ask: float | None) -> dict[str, Any]:
    return {
        "snapshotTime": ts,
        "snapshotTimeUTC": ts,
        "closePrice": {"bid": bid, "ask": ask},
        "openPrice": {"bid": bid, "ask": ask},
    }


@pytest.fixture
def client() -> Iterator[CollectorClient]:
    with CollectorClient("collector.test", 8001, scheme="http") as c:
        yield c


@pytest.fixture
def gateway(client: CollectorClient) -> CollectorGateway:
    return CollectorGateway(client, wait=wait_none())


@respx.mock(base_url=BASE)
async def test_catalog_union_of_us_catalogs(
    respx_mock: respx.MockRouter, gateway: CollectorGateway
) -> None:
    respx_mock.get("/api/v1/markets/shares").respond(json=REGIONS)

    def shares(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["region"] == "us"
        assert body["max_doc"] == 500
        epics = {"most_traded": ["TSLA", "AAPL"], "top_gainers": ["TSLA", "SPX"]}
        items = [
            market(e, "INDICES" if e == "SPX" else "SHARES") for e in epics.get(body["catalog"], [])
        ]
        return httpx.Response(200, json={"nodes": [], "markets": items})

    route = respx_mock.post("/api/v1/markets/shares").mock(side_effect=shares)
    markets = await gateway.list_catalog_markets()
    assert route.call_count == 4
    assert [m.epic for m in markets] == ["TSLA", "AAPL", "TSLA", "SPX"]
    assert all(m.source is Source.CATALOG for m in markets)
    assert markets[0].name == "TSLA Inc"
    assert markets[3].instrument_type == "INDICES"


@respx.mock(base_url=BASE)
async def test_no_us_catalogs_is_incomplete_data(
    respx_mock: respx.MockRouter, gateway: CollectorGateway
) -> None:
    respx_mock.get("/api/v1/markets/shares").respond(json=[REGIONS[2]])
    with pytest.raises(CollectorIncompleteData):
        await gateway.list_catalog_markets()


@respx.mock(base_url=BASE)
async def test_catalog_4xx_is_incomplete_data(
    respx_mock: respx.MockRouter, gateway: CollectorGateway
) -> None:
    respx_mock.get("/api/v1/markets/shares").respond(json=REGIONS)
    respx_mock.post("/api/v1/markets/shares").respond(404, json={"detail": "nope"})
    with pytest.raises(CollectorIncompleteData, match="HTTP 404"):
        await gateway.list_catalog_markets()


@respx.mock(base_url=BASE)
async def test_search_in_batches_of_50_with_bisection(
    respx_mock: respx.MockRouter, gateway: CollectorGateway
) -> None:
    sizes: list[int] = []
    lock = threading.Lock()

    def search(request: httpx.Request) -> httpx.Response:
        epics = json.loads(request.content)["epics"].split(",")
        with lock:
            sizes.append(len(epics))
        if "BAD" in epics:
            return httpx.Response(400, json={"detail": "invalid epic"})
        known = [e for e in epics if not e.startswith("UNKNOWN")]
        return httpx.Response(200, json={"marketDetails": [detail(e) for e in known]})

    respx_mock.post("/api/v1/search-markets").mock(side_effect=search)
    epics = [f"E{i:03d}" for i in range(110)] + ["BAD", "UNKNOWN1"]
    found = await gateway.lookup_markets(epics)
    assert max(sizes) == 50
    assert len(found) == 110
    assert all(m.source is Source.SWEEP and m.currency == "USD" for m in found)
    assert found[0].opening_hours is not None
    assert found[0].opening_hours.zone == "UTC"
    assert found[0].opening_hours.days["mon"] == ("13:30 - 20:00",)


@respx.mock(base_url=BASE)
async def test_hourly_prices(respx_mock: respx.MockRouter, gateway: CollectorGateway) -> None:
    route = respx_mock.post("/api/v1/prices").respond(
        json={
            "prices": [
                price("2026-09-10T14:00:00", 101.0, 101.2),
                price("2026-09-10T13:00:00", 100.0, 100.2),
                price("2026-09-10T15:00:00", None, 100.2),
            ],
            "instrumentType": "SHARES",
        }
    )
    history = await gateway.hourly_history("AAPL", START, END)
    body = json.loads(route.calls.last.request.content)
    assert body["epic"] == "AAPL"
    assert body["resolution"] == "HOUR"
    assert body["from"] == "2026-09-10T13:00:00"
    assert body["to"] == "2026-10-07T20:00:00"
    assert body["max_doc"] >= 20 * 7
    assert history.error is None
    assert [(b.ts.hour, b.mid) for b in history.bars] == [(13, 100.1), (14, 101.1)]
    assert history.bars[0].ts.tzinfo is UTC


@respx.mock(base_url=BASE)
async def test_prices_404_means_no_history_and_is_not_retried(
    respx_mock: respx.MockRouter, gateway: CollectorGateway
) -> None:
    route = respx_mock.post("/api/v1/prices").respond(404, json={"detail": "not found"})
    history = await gateway.hourly_history("BIL", START, END)
    assert history.error == NO_HISTORY
    assert route.call_count == 1


@respx.mock(base_url=BASE)
async def test_empty_prices(respx_mock: respx.MockRouter, gateway: CollectorGateway) -> None:
    respx_mock.post("/api/v1/prices").respond(json={"prices": []})
    assert (await gateway.hourly_history("X", START, END)).error == (
        "Capital.com returned no bars in window"
    )


@pytest.mark.parametrize(
    "outcome",
    [httpx.ConnectError("refused"), httpx.Response(502), httpx.Response(429)],
)
@respx.mock(base_url=BASE)
async def test_retries_five_times_then_unavailable(
    respx_mock: respx.MockRouter,
    gateway: CollectorGateway,
    outcome: httpx.Response | Exception,
) -> None:
    def answer(_: httpx.Request) -> httpx.Response:
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    route = respx_mock.post("/api/v1/prices").mock(side_effect=answer)
    with pytest.raises(CollectorUnavailable):
        await gateway.hourly_history("AAPL", START, END)
    assert route.call_count == 5


@respx.mock(base_url=BASE)
async def test_at_most_four_concurrent_price_calls(
    respx_mock: respx.MockRouter, gateway: CollectorGateway
) -> None:
    lock = threading.Lock()
    state = {"now": 0, "max": 0}

    def slow(_: httpx.Request) -> httpx.Response:
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        with lock:
            state["now"] -= 1
        return httpx.Response(200, json={"prices": [price("2026-09-10T13:00:00", 1.0, 1.1)]})

    respx_mock.post("/api/v1/prices").mock(side_effect=slow)
    await asyncio.gather(*(gateway.hourly_history(f"E{i}", START, END) for i in range(12)))
    assert state["max"] == 4
