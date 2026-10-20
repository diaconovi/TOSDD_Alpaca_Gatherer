"""``AlpacaGateway`` against recorded Alpaca responses (respx intercepts httpx)."""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from tenacity import wait_none

from alpaca_gatherer.domain.credentials import PlainCredentials
from alpaca_gatherer.domain.errors import AlpacaAuthFailed, AlpacaUnavailable
from alpaca_gatherer.domain.matching.models import AlpacaBar
from alpaca_gatherer.infrastructure.clients.alpaca import AlpacaGateway

FIXTURES = Path(__file__).parents[1] / "fixtures" / "alpaca"
TRADING = "https://paper.alpaca.test"
DATA = "https://data.alpaca.test"
CREDS = PlainCredentials("PKCONTRACTKEY123", "contract-secret-value-456")
START = datetime(2026, 10, 7, 13, tzinfo=UTC)
END = datetime(2026, 10, 7, 20, tzinfo=UTC)


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
async def gateway() -> AsyncIterator[AlpacaGateway]:
    gw = AlpacaGateway(TRADING, DATA, wait=wait_none())
    yield gw
    await gw.aclose()


def assert_auth_headers(request: httpx.Request) -> None:
    assert request.headers["APCA-API-KEY-ID"] == CREDS.api_key
    assert request.headers["APCA-API-SECRET-KEY"] == CREDS.api_secret


@respx.mock
async def test_assets_keep_every_status(gateway: AlpacaGateway) -> None:
    route = respx.get(f"{TRADING}/v2/assets", params={"asset_class": "us_equity"}).respond(
        json=fixture("assets.json")
    )
    assets = await gateway.list_assets(CREDS)
    assert_auth_headers(route.calls.last.request)
    by_symbol = {a.symbol: a for a in assets}
    assert set(by_symbol) == {"TSLA", "BRK.B", "CHSN", "TCBI.PRB"}
    assert by_symbol["CHSN"].active
    assert not by_symbol["CHSN"].tradable
    assert not by_symbol["TCBI.PRB"].active
    assert by_symbol["BRK.B"].name == "Berkshire Hathaway Inc. Class B"


@respx.mock
async def test_calendar_converts_new_york_times_to_utc(gateway: AlpacaGateway) -> None:
    route = respx.get(f"{TRADING}/v2/calendar").respond(json=fixture("calendar.json"))
    sessions = await gateway.calendar(CREDS, date(2026, 10, 1), date(2026, 11, 30))
    assert route.calls.last.request.url.params["start"] == "2026-10-01"
    assert route.calls.last.request.url.params["end"] == "2026-11-30"
    assert [(s.open.hour, s.open.minute, s.close.hour) for s in sessions] == [
        (13, 30, 20),  # EDT
        (14, 30, 21),  # EST after the DST change
        (14, 30, 18),  # half day
    ]
    assert all(s.open.tzinfo is UTC for s in sessions)


@respx.mock
async def test_bars_parameters_and_pagination(gateway: AlpacaGateway) -> None:
    route = respx.get(f"{DATA}/v2/stocks/bars").mock(
        side_effect=[
            httpx.Response(200, json=fixture("bars_page1.json")),
            httpx.Response(200, json=fixture("bars_page2.json")),
        ]
    )
    bars = await gateway.hourly_bars(CREDS, ["TSLA", "BRK.B"], START, END, "iex")
    first, second = (c.request for c in route.calls)
    params = first.url.params
    assert params["symbols"] == "BRK.B,TSLA"
    assert params["timeframe"] == "1Hour"
    assert params["adjustment"] == "raw"
    assert params["feed"] == "iex"
    assert params["start"] == "2026-10-07T13:00:00Z"
    assert params["end"] == "2026-10-07T20:00:00Z"
    assert "page_token" not in params
    assert second.url.params["page_token"] == "VFNMQXwyMDI2LTEwLTA3VDE0OjAwOjAwWg=="
    assert_auth_headers(second)
    assert [b.close for b in bars["TSLA"]] == [432.4, 434.1, 433.9]
    assert bars["BRK.B"] == [AlpacaBar(START, 470.6)]


@respx.mock
async def test_bars_100_symbols_per_request(gateway: AlpacaGateway) -> None:
    route = respx.get(f"{DATA}/v2/stocks/bars").respond(json={"bars": {}, "next_page_token": None})
    symbols = [f"S{i:03d}" for i in range(250)]
    assert await gateway.hourly_bars(CREDS, symbols, START, END, "sip") == {}
    sizes = [len(c.request.url.params["symbols"].split(",")) for c in route.calls]
    assert sizes == [100, 100, 50]


@respx.mock
async def test_bad_symbol_is_bisected_out(gateway: AlpacaGateway) -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        symbols = request.url.params["symbols"].split(",")
        if "BAD/SYM" in symbols:
            return httpx.Response(400, json={"message": "invalid symbol"})
        return httpx.Response(
            200,
            json={"bars": {s: [{"t": "2026-10-07T13:00:00Z", "c": 1.0}] for s in symbols}},
        )

    respx.get(f"{DATA}/v2/stocks/bars").mock(side_effect=answer)
    bars = await gateway.hourly_bars(CREDS, ["AAA", "BAD/SYM", "CCC", "DDD"], START, END, "sip")
    assert set(bars) == {"AAA", "CCC", "DDD"}


@pytest.mark.parametrize("status", [401, 403])
@respx.mock
async def test_auth_errors(gateway: AlpacaGateway, status: int) -> None:
    route = respx.get(f"{TRADING}/v2/assets").respond(status, json={"message": "forbidden"})
    with pytest.raises(AlpacaAuthFailed):
        await gateway.list_assets(CREDS)
    assert route.call_count == 1


@respx.mock
async def test_retries_429_then_succeeds(gateway: AlpacaGateway) -> None:
    route = respx.get(f"{TRADING}/v2/assets").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(200, json=fixture("assets.json")),
        ]
    )
    assert len(await gateway.list_assets(CREDS)) == 4
    assert route.call_count == 3


@pytest.mark.parametrize(
    "outcome", [httpx.Response(500), httpx.Response(429), httpx.ConnectError("refused")]
)
@respx.mock
async def test_gives_up_after_five_attempts(
    gateway: AlpacaGateway, outcome: httpx.Response | Exception
) -> None:
    route = respx.get(f"{TRADING}/v2/calendar").mock(side_effect=lambda _: _raise_or(outcome))
    with pytest.raises(AlpacaUnavailable):
        await gateway.calendar(CREDS, date(2026, 10, 1), date(2026, 10, 2))
    assert route.call_count == 5


def _raise_or(outcome: httpx.Response | Exception) -> httpx.Response:
    if isinstance(outcome, Exception):
        raise outcome
    return outcome


@respx.mock
async def test_other_client_errors_and_garbage(gateway: AlpacaGateway) -> None:
    respx.get(f"{TRADING}/v2/assets").respond(404)
    with pytest.raises(AlpacaUnavailable, match="HTTP 404"):
        await gateway.list_assets(CREDS)
    respx.get(f"{TRADING}/v2/calendar").respond(200, text="<html>")
    with pytest.raises(AlpacaUnavailable, match="non-JSON"):
        await gateway.calendar(CREDS, date(2026, 10, 1), date(2026, 10, 2))


@respx.mock
async def test_credentials_never_logged(
    gateway: AlpacaGateway, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    respx.get(f"{TRADING}/v2/assets").mock(side_effect=[httpx.Response(503), httpx.Response(401)])
    with pytest.raises(AlpacaAuthFailed) as info:
        await gateway.list_assets(CREDS)
    for secret in (CREDS.api_key, CREDS.api_secret):
        assert secret not in caplog.text
        assert secret not in str(info.value)
