"""Synthetic market data for matching tests: sessions, bars, instruments and assets."""

import math
import random
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from alpaca_gatherer.domain.mapping import CandidateKind, Source
from alpaca_gatherer.domain.matching.candidates import CandidateRef
from alpaca_gatherer.domain.matching.models import (
    AlpacaAsset,
    AlpacaBar,
    CapitalBar,
    CapitalHistory,
    CapitalInstrument,
    OpeningHours,
    Session,
)

US_HOURS = OpeningHours(
    "UTC", dict.fromkeys(("mon", "tue", "wed", "thu", "fri"), ("13:30 - 20:00",))
)


def weekdays(start: date, count: int) -> list[date]:
    days: list[date] = []
    day = start
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def sessions(count: int, start: date = date(2026, 9, 14)) -> list[Session]:
    """``count`` regular sessions 13:30-20:00 UTC on consecutive weekdays."""
    return [
        Session(
            datetime(d.year, d.month, d.day, 13, 30, tzinfo=UTC),
            datetime(d.year, d.month, d.day, 20, 0, tzinfo=UTC),
        )
        for d in weekdays(start, count)
    ]


def session_hours(all_sessions: Sequence[Session]) -> list[datetime]:
    """Hourly bar starts inside the sessions: 13:00 … 19:00 UTC (7 per session)."""
    out: list[datetime] = []
    for s in all_sessions:
        ts = s.open.replace(minute=0)
        while ts < s.close:
            out.append(ts)
            ts += timedelta(hours=1)
    return out


def walk(n: int, start: float = 100.0, vol: float = 0.01, seed: int = 1) -> list[float]:
    """A deterministic geometric random walk."""
    rng = random.Random(seed)
    prices = [start]
    for _ in range(n - 1):
        prices.append(prices[-1] * math.exp(rng.gauss(0, vol)))
    return prices


def capital_bars(
    times: Sequence[datetime], mids: Sequence[float], spread_pct: float = 0.1
) -> tuple[CapitalBar, ...]:
    return tuple(
        CapitalBar(ts, bid=m * (1 - spread_pct / 200), ask=m * (1 + spread_pct / 200))
        for ts, m in zip(times, mids, strict=True)
    )


def alpaca_bars(times: Sequence[datetime], closes: Sequence[float]) -> list[AlpacaBar]:
    return [AlpacaBar(ts, c) for ts, c in zip(times, closes, strict=True)]


def history(bars: tuple[CapitalBar, ...]) -> CapitalHistory:
    return CapitalHistory(bars)


def instrument(
    epic: str,
    symbol: str | None = None,
    name: str | None = None,
    source: Source = Source.CATALOG,
) -> CapitalInstrument:
    return CapitalInstrument(
        epic=epic,
        symbol=symbol if symbol is not None else epic,
        name=name if name is not None else f"{epic} Corp",
        instrument_type="SHARES",
        source=source,
        currency="USD",
        opening_hours=US_HOURS,
    )


def asset(
    symbol: str, name: str | None = None, active: bool = True, tradable: bool = True
) -> AlpacaAsset:
    return AlpacaAsset(
        symbol, name if name is not None else f"{symbol} Corp", "NYSE", active, tradable
    )


def ref(
    symbol: str,
    kind: CandidateKind = CandidateKind.EXACT,
    *,
    active: bool = True,
    tradable: bool = True,
) -> CandidateRef:
    return CandidateRef(symbol, kind, asset(symbol, active=active, tradable=tradable))
