"""``AlpacaGateway``: Alpaca assets, calendar and hourly bars over async httpx (research R3).

Credentials travel only in the ``APCA-API-KEY-ID`` / ``APCA-API-SECRET-KEY`` request headers; they
are never logged or put into error messages.
"""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from tenacity.wait import wait_base

from alpaca_gatherer.domain.credentials import PlainCredentials
from alpaca_gatherer.domain.errors import AlpacaAuthFailed, AlpacaUnavailable
from alpaca_gatherer.domain.matching.models import AlpacaAsset, AlpacaBar, Session, utc
from alpaca_gatherer.domain.thresholds import Feed
from alpaca_gatherer.infrastructure.clients.retry import (
    DEFAULT_WAIT,
    is_retryable_status,
    retrying,
)

__all__ = ["AlpacaGateway"]

log = logging.getLogger(__name__)

NEW_YORK = ZoneInfo("America/New_York")
SYMBOLS_PER_REQUEST = 100
BARS_PAGE_LIMIT = 10000


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Asset(_Model):
    symbol: str
    name: str | None = None
    exchange: str | None = None
    status: str = "inactive"
    tradable: bool = False


class _CalendarDay(_Model):
    date: date
    open: time
    close: time


class _Bar(_Model):
    t: datetime
    c: float


class _BarsPage(_Model):
    bars: dict[str, list[_Bar]] | None = None
    next_page_token: str | None = Field(default=None)


_ASSETS = TypeAdapter(list[_Asset])
_CALENDAR = TypeAdapter(list[_CalendarDay])


class _RetryableStatus(Exception):
    """An HTTP 429/5xx answer, raised so the retry policy can retry it."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


class _ClientError(Exception):
    """A non-retryable 4xx answer other than 401/403."""

    def __init__(self, status: int) -> None:
        super().__init__(f"HTTP {status}")
        self.status = status


def _retryable(exc: BaseException) -> bool:
    return isinstance(exc, _RetryableStatus | httpx.TransportError)


def _iso(value: datetime) -> str:
    return utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlpacaGateway:
    """Implements ``AlpacaMarketPort`` with ``httpx.AsyncClient``."""

    def __init__(
        self,
        trading_url: str,
        data_url: str,
        *,
        http: httpx.AsyncClient | None = None,
        wait: wait_base = DEFAULT_WAIT,
        symbols_per_request: int = SYMBOLS_PER_REQUEST,
    ) -> None:
        self._trading = trading_url.rstrip("/")
        self._data = data_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
        self._wait = wait
        self._chunk = symbols_per_request

    async def _get(
        self, credentials: PlainCredentials, url: str, params: Mapping[str, str]
    ) -> Any:  # JSON payload, validated by the caller's pydantic model
        headers = {
            "APCA-API-KEY-ID": credentials.api_key,
            "APCA-API-SECRET-KEY": credentials.api_secret,
        }
        path = url.removeprefix(self._trading).removeprefix(self._data)
        try:
            async for attempt in retrying(_retryable, wait=self._wait):
                with attempt:
                    response = await self._http.get(url, params=params, headers=headers)
                    if is_retryable_status(response.status_code):
                        raise _RetryableStatus(response.status_code)
        except _RetryableStatus as exc:
            raise AlpacaUnavailable(f"{path}: Alpaca kept answering HTTP {exc.status}") from None
        except httpx.TransportError as exc:
            raise AlpacaUnavailable(
                f"{path}: Alpaca could not be reached ({type(exc).__name__})"
            ) from None
        if response.status_code in (401, 403):
            raise AlpacaAuthFailed()
        if response.is_error:
            raise _ClientError(response.status_code)
        try:
            return response.json()
        except ValueError:
            raise AlpacaUnavailable(f"{path}: Alpaca returned a non-JSON body") from None

    async def _get_or_fail(
        self, credentials: PlainCredentials, url: str, params: Mapping[str, str]
    ) -> Any:  # JSON payload, validated by the caller's pydantic model
        try:
            return await self._get(credentials, url, params)
        except _ClientError as exc:
            path = url.removeprefix(self._trading).removeprefix(self._data)
            raise AlpacaUnavailable(f"{path}: Alpaca answered HTTP {exc.status}") from None

    async def list_assets(self, credentials: PlainCredentials) -> list[AlpacaAsset]:
        """Every ``us_equity`` asset, all statuses."""
        raw = await self._get_or_fail(
            credentials, f"{self._trading}/v2/assets", {"asset_class": "us_equity"}
        )
        try:
            assets = _ASSETS.validate_python(raw)
        except ValidationError:
            raise AlpacaUnavailable("/v2/assets: malformed response") from None
        return [
            AlpacaAsset(
                symbol=a.symbol,
                name=a.name or "",
                exchange=a.exchange or "",
                active=a.status == "active",
                tradable=a.tradable,
            )
            for a in assets
        ]

    async def calendar(
        self, credentials: PlainCredentials, start: date, end: date
    ) -> list[Session]:
        """Regular sessions between two dates, as UTC instants."""
        raw = await self._get_or_fail(
            credentials,
            f"{self._trading}/v2/calendar",
            {"start": start.isoformat(), "end": end.isoformat()},
        )
        try:
            days = _CALENDAR.validate_python(raw)
        except ValidationError:
            raise AlpacaUnavailable("/v2/calendar: malformed response") from None
        return [
            Session(
                datetime.combine(d.date, d.open, NEW_YORK).astimezone(UTC),
                datetime.combine(d.date, d.close, NEW_YORK).astimezone(UTC),
            )
            for d in sorted(days, key=lambda d: d.date)
        ]

    async def hourly_bars(
        self,
        credentials: PlainCredentials,
        symbols: Sequence[str],
        start: datetime,
        end: datetime,
        feed: Feed,
    ) -> dict[str, list[AlpacaBar]]:
        """Raw (unadjusted) hourly bars, 100 symbols per request, following pagination."""
        unique = sorted(set(symbols))
        out: dict[str, list[AlpacaBar]] = {}
        chunks = [unique[i : i + self._chunk] for i in range(0, len(unique), self._chunk)]
        for n, chunk in enumerate(chunks, 1):
            out.update(await self._bars_chunk(credentials, chunk, start, end, feed))
            if n % 20 == 0:
                log.info("Alpaca bars: %d/%d requests", n, len(chunks))
        return out

    async def _bars_chunk(
        self,
        credentials: PlainCredentials,
        symbols: list[str],
        start: datetime,
        end: datetime,
        feed: Feed,
    ) -> dict[str, list[AlpacaBar]]:
        """Bars of one symbol batch; a 400/422 is bisected so one bad symbol is skipped alone."""
        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Hour",
            "start": _iso(start),
            "end": _iso(end),
            "adjustment": "raw",
            "feed": feed,
            "limit": str(BARS_PAGE_LIMIT),
        }
        out: dict[str, list[AlpacaBar]] = {}
        token: str | None = None
        while True:
            page_params = {**params, "page_token": token} if token else params
            try:
                raw = await self._get(credentials, f"{self._data}/v2/stocks/bars", page_params)
            except _ClientError as exc:
                if exc.status in (400, 422) and len(symbols) > 1:
                    mid = len(symbols) // 2
                    left, right = await asyncio.gather(
                        self._bars_chunk(credentials, symbols[:mid], start, end, feed),
                        self._bars_chunk(credentials, symbols[mid:], start, end, feed),
                    )
                    return {**left, **right}
                log.warning("Alpaca bars skipped for %s (HTTP %d)", ",".join(symbols), exc.status)
                return {}
            try:
                page = _BarsPage.model_validate(raw)
            except ValidationError:
                raise AlpacaUnavailable("/v2/stocks/bars: malformed response") from None
            for symbol, bars in (page.bars or {}).items():
                out.setdefault(symbol, []).extend(AlpacaBar(utc(b.t), b.c) for b in bars)
            token = page.next_page_token
            if not token:
                return out

    async def aclose(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()
