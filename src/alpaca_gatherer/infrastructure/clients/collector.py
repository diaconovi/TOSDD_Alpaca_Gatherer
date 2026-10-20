"""``CollectorGateway``: Capital.com data through the collector's official client.

The client is synchronous, so each call runs in a worker thread; at most ``concurrency`` calls are
in flight at once (the collector also rate-limits globally). Raw JSON is parsed into pydantic
models here and converted into domain types; nothing else sees collector payloads.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import datetime
from functools import partial
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from tenacity.wait import wait_base
from to_collector_client import (
    CollectorAPIError,
    CollectorClient,
    CollectorConnectionError,
    CollectorHTTPError,
    CollectorServerError,
    Resolution,
)

from alpaca_gatherer.domain.errors import CollectorIncompleteData, CollectorUnavailable
from alpaca_gatherer.domain.mapping import Source
from alpaca_gatherer.domain.matching.models import (
    CapitalBar,
    CapitalHistory,
    CapitalInstrument,
    OpeningHours,
    utc,
)
from alpaca_gatherer.infrastructure.clients.retry import DEFAULT_WAIT, retrying

__all__ = ["CollectorGateway"]

log = logging.getLogger(__name__)

US_REGION = "us"
CATALOG_SIZE = 500
EPICS_PER_CALL = 50
NO_HISTORY = "Capital.com has no HOUR price history for this epic (HTTP 404)"
NO_BARS = "Capital.com returned no bars in window"


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class _CatalogRef(_Model):
    name: str


class _Region(_Model):
    name: str
    catalog: list[_CatalogRef] = Field(default_factory=list)


class _CatalogMarket(_Model):
    epic: str
    symbol: str | None = None
    instrument_name: str | None = Field(default=None, alias="instrumentName")
    instrument_type: str | None = Field(default=None, alias="instrumentType")


class _SharesMarket(_Model):
    markets: list[_CatalogMarket] = Field(default_factory=list)


class _Instrument(_Model):
    epic: str
    symbol: str | None = None
    name: str | None = None
    type: str | None = None
    currency: str | None = None
    opening_hours: dict[str, Any] | None = Field(default=None, alias="openingHours")


class _MarketDetail(_Model):
    instrument: _Instrument


class _SearchResult(_Model):
    market_details: list[_MarketDetail] = Field(default_factory=list, alias="marketDetails")


class _Quote(_Model):
    bid: float | None = None
    ask: float | None = None


class _Price(_Model):
    snapshot_time_utc: datetime = Field(alias="snapshotTimeUTC")
    close_price: _Quote | None = Field(default=None, alias="closePrice")


class _Prices(_Model):
    prices: list[_Price] = Field(default_factory=list)


_REGIONS = TypeAdapter(list[_Region])


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, CollectorConnectionError | CollectorServerError):
        return True
    return isinstance(exc, CollectorHTTPError) and exc.status_code == 429


def _unavailable(what: str, exc: BaseException) -> CollectorUnavailable:
    if isinstance(exc, CollectorConnectionError):
        return CollectorUnavailable(f"{what}: the collector could not be reached")
    status = exc.status_code if isinstance(exc, CollectorAPIError) else "?"
    return CollectorUnavailable(f"{what}: the collector kept answering HTTP {status}")


def _opening_hours(raw: dict[str, Any] | None) -> OpeningHours | None:
    if raw is None:
        return None
    days = {
        day: tuple(str(i) for i in intervals)
        for day, intervals in raw.items()
        if day != "zone" and isinstance(intervals, list)
    }
    return OpeningHours(str(raw.get("zone") or "UTC"), days)


class CollectorGateway:
    """Implements ``CapitalCatalogPort`` over ``to_collector_client.CollectorClient``."""

    def __init__(
        self,
        client: CollectorClient,
        *,
        concurrency: int = 4,
        wait: wait_base = DEFAULT_WAIT,
    ) -> None:
        self._client = client
        self._semaphore = asyncio.Semaphore(concurrency)
        self._wait = wait

    async def _call[T](self, what: str, fn: Callable[[], T]) -> T:
        """Run one client call in a thread, with retries; retryable failures that persist
        become ``CollectorUnavailable``; other API errors are re-raised for the caller."""
        try:
            async for attempt in retrying(_retryable, wait=self._wait):
                with attempt:
                    async with self._semaphore:
                        return await asyncio.to_thread(fn)
        except CollectorAPIError as exc:
            if _retryable(exc):
                raise _unavailable(what, exc) from None
            raise
        except CollectorConnectionError as exc:
            raise _unavailable(what, exc) from None
        raise AssertionError("unreachable")  # pragma: no cover - retrying always returns/raises

    async def list_catalog_markets(self) -> list[CapitalInstrument]:
        """Every market of the four US share catalogs (each capped at 500 by Capital.com)."""
        try:
            raw = await self._call("discover catalogs", self._client.discover_market_catalogs)
            regions = _REGIONS.validate_python(raw)
        except (CollectorAPIError, ValidationError) as exc:
            raise CollectorIncompleteData(
                f"catalog discovery failed ({type(exc).__name__})"
            ) from None
        names = [c.name for r in regions if r.name.lower() == US_REGION for c in r.catalog]
        if not names:
            raise CollectorIncompleteData("the collector lists no US share catalogs")
        out: list[CapitalInstrument] = []
        for name in names:
            try:
                raw_market = await self._call(
                    f"catalog {name}",
                    partial(self._client.get_shares_market, US_REGION, name, max_doc=CATALOG_SIZE),
                )
                market = _SharesMarket.model_validate(raw_market)
            except CollectorAPIError as exc:
                raise CollectorIncompleteData(
                    f"catalog {name} failed with HTTP {exc.status_code}"
                ) from None
            except ValidationError:
                raise CollectorIncompleteData(f"catalog {name} returned malformed data") from None
            if len(market.markets) >= CATALOG_SIZE:
                log.info("catalog %s hit the %d cap; the sweep completes it", name, CATALOG_SIZE)
            out += [
                CapitalInstrument(
                    epic=m.epic,
                    symbol=m.symbol or m.epic,
                    name=m.instrument_name,
                    instrument_type=m.instrument_type,
                    source=Source.CATALOG,
                )
                for m in market.markets
            ]
        log.info("US catalogs %s: %d markets", ", ".join(names), len(out))
        return out

    async def lookup_markets(self, epics: Sequence[str]) -> list[CapitalInstrument]:
        """Look up epics 50 per call (unknown epics are silently dropped by Capital.com)."""
        unique = sorted(set(epics))
        batches = [unique[i : i + EPICS_PER_CALL] for i in range(0, len(unique), EPICS_PER_CALL)]
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(self._lookup_batch(batch)) for batch in batches]
        found: dict[str, CapitalInstrument] = {}
        for task in tasks:
            for detail in task.result():
                inst = detail.instrument
                found[inst.epic] = CapitalInstrument(
                    epic=inst.epic,
                    symbol=inst.symbol or inst.epic,
                    name=inst.name,
                    instrument_type=inst.type,
                    source=Source.SWEEP,
                    currency=inst.currency,
                    opening_hours=_opening_hours(inst.opening_hours),
                )
        log.info("epic sweep: %d of %d spellings exist", len(found), len(unique))
        return [found[e] for e in sorted(found)]

    async def _lookup_batch(self, batch: list[str]) -> list[_MarketDetail]:
        """One ``search_markets`` call; a 400 is bisected so one bad epic cannot hide the rest."""
        try:
            raw = await self._call(
                f"search {len(batch)} epics",
                lambda: self._client.search_markets(epics=",".join(batch)),
            )
        except CollectorAPIError as exc:
            if exc.status_code == 400 and len(batch) > 1:
                mid = len(batch) // 2
                left, right = await asyncio.gather(
                    self._lookup_batch(batch[:mid]), self._lookup_batch(batch[mid:])
                )
                return left + right
            log.warning("epic lookup failed for %s… (HTTP %s)", batch[0], exc.status_code)
            return []
        try:
            return _SearchResult.model_validate(raw).market_details
        except ValidationError:
            log.warning("epic lookup for %s… returned malformed data", batch[0])
            return []

    async def hourly_history(self, epic: str, start: datetime, end: datetime) -> CapitalHistory:
        """Hourly bid/ask closes of ``epic`` in ``[start, end]`` (UTC)."""
        start_utc, end_utc = utc(start), utc(end)
        max_doc = max(1, int((end_utc - start_utc).total_seconds() // 3600) + 1)
        try:
            raw = await self._call(
                f"prices {epic}",
                lambda: self._client.get_prices(
                    epic,
                    resolution=Resolution.HOUR,
                    max_doc=max_doc,
                    from_=start_utc.replace(tzinfo=None),
                    to=end_utc.replace(tzinfo=None),
                ),
            )
        except CollectorAPIError as exc:
            if exc.status_code == 404:
                return CapitalHistory.missing(NO_HISTORY)
            return CapitalHistory.missing(
                f"Capital.com price request failed (HTTP {exc.status_code})"
            )
        try:
            prices = _Prices.model_validate(raw).prices
        except ValidationError:
            return CapitalHistory.missing("Capital.com returned malformed prices")
        bars = tuple(
            CapitalBar(utc(p.snapshot_time_utc), p.close_price.bid, p.close_price.ask)
            for p in prices
            if p.close_price is not None
            and p.close_price.bid is not None
            and p.close_price.ask is not None
        )
        if not bars:
            return CapitalHistory.missing(NO_BARS)
        return CapitalHistory(tuple(sorted(bars, key=lambda b: b.ts)))

    async def aclose(self) -> None:
        """Close the collector client's HTTP connection."""
        await asyncio.to_thread(self._client.close)
