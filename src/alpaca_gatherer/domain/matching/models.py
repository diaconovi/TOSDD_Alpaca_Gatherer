"""Market-data value types consumed by the matching domain.

Adapters translate broker responses into these types; the matching functions never see raw JSON.

>>> bar = CapitalBar(datetime(2026, 10, 7, 14, tzinfo=UTC), bid=99.0, ask=101.0)
>>> bar.mid, bar.rel_spread
(100.0, 0.02)
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime

from alpaca_gatherer.domain.mapping import Source

__all__ = [
    "AlpacaAsset",
    "AlpacaBar",
    "CapitalBar",
    "CapitalHistory",
    "CapitalInstrument",
    "OpeningHours",
    "Session",
]


@dataclass(frozen=True, slots=True)
class OpeningHours:
    """Capital.com opening hours: a zone and, per weekday (``mon``…``sun``), ``HH:MM - HH:MM``."""

    zone: str
    days: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CapitalInstrument:
    """A Capital.com market as reported by the collector."""

    epic: str
    symbol: str | None
    name: str | None
    instrument_type: str | None
    source: Source
    currency: str | None = None
    opening_hours: OpeningHours | None = None


@dataclass(frozen=True, slots=True)
class AlpacaAsset:
    """An Alpaca ``us_equity`` asset (any status)."""

    symbol: str
    name: str
    exchange: str
    active: bool
    tradable: bool


@dataclass(frozen=True, slots=True)
class Session:
    """A regular US trading session, as UTC open and close instants."""

    open: datetime
    close: datetime

    def __post_init__(self) -> None:
        if self.open.tzinfo is None or self.close.tzinfo is None:
            raise ValueError("session times must be timezone-aware")
        if self.close <= self.open:
            raise ValueError("session close must be after open")


@dataclass(frozen=True, slots=True)
class CapitalBar:
    """An hourly Capital.com bar: UTC start time and closing bid/ask."""

    ts: datetime
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        """Mid close ``(bid + ask) / 2``."""
        return (self.bid + self.ask) / 2

    @property
    def rel_spread(self) -> float:
        """Relative spread ``(ask - bid) / mid`` (``nan`` when the mid is zero)."""
        mid = self.mid
        return (self.ask - self.bid) / mid if mid else float("nan")


@dataclass(frozen=True, slots=True)
class CapitalHistory:
    """Hourly history of one epic, or why there is none (``error``)."""

    bars: tuple[CapitalBar, ...] = ()
    error: str | None = None

    @classmethod
    def missing(cls, detail: str) -> CapitalHistory:
        """History that could not be obtained, with a human-readable reason."""
        return cls((), detail)


@dataclass(frozen=True, slots=True)
class AlpacaBar:
    """An hourly Alpaca bar: UTC start time and close (last trade)."""

    ts: datetime
    close: float


def utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime (naive values are taken as UTC).

    >>> utc(datetime(2026, 1, 1)).tzinfo
    datetime.timezone.utc
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
