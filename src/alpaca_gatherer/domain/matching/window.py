"""Comparison window: session selection, regular-session filtering and bar alignment.

The window is the last ``sessions`` complete US sessions, each closed at least ``embargo_minutes``
before the window end. Both brokers are queried over ``[floor(first open), last close]`` and only
bars that start inside a regular session are compared, joined on identical UTC timestamps.

>>> s = Session(datetime(2026, 10, 7, 13, 30, tzinfo=UTC), datetime(2026, 10, 7, 20, tzinfo=UTC))
>>> query_range([s])
(datetime.datetime(2026, 10, 7, 13, 0, tzinfo=datetime.timezone.utc), \
datetime.datetime(2026, 10, 7, 20, 0, tzinfo=datetime.timezone.utc))
"""

from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from alpaca_gatherer.domain.errors import AlpacaUnavailable
from alpaca_gatherer.domain.matching.models import AlpacaBar, CapitalBar, Session

__all__ = [
    "AlignedBar",
    "Alignment",
    "SessionLocator",
    "align",
    "calendar_range",
    "floor_hour",
    "query_range",
    "select_sessions",
]


def floor_hour(value: datetime) -> datetime:
    """Truncate to the hour."""
    return value.replace(minute=0, second=0, microsecond=0)


def calendar_range(window_end: datetime, sessions: int) -> tuple[date, date]:
    """Calendar dates to request so that ``sessions`` complete sessions are surely included."""
    end = window_end.astimezone(UTC)
    return (end - timedelta(days=sessions * 2 + 10)).date(), end.date()


def select_sessions(
    calendar: Iterable[Session], window_end: datetime, count: int, embargo_minutes: int
) -> list[Session]:
    """The last ``count`` sessions that closed at least ``embargo_minutes`` before ``window_end``.

    Raises ``AlpacaUnavailable`` if the calendar does not hold enough complete sessions.
    """
    margin = timedelta(minutes=embargo_minutes)
    complete = sorted((s for s in calendar if s.close + margin <= window_end), key=lambda s: s.open)
    if len(complete) < count:
        raise AlpacaUnavailable(
            f"the Alpaca calendar has only {len(complete)} complete sessions; {count} are needed"
        )
    return complete[-count:]


def query_range(sessions: Sequence[Session]) -> tuple[datetime, datetime]:
    """UTC range queried from both brokers: ``[floor(first open), last close]``."""
    return floor_hour(sessions[0].open), sessions[-1].close


class SessionLocator:
    """Finds the session a bar belongs to: bar start in ``[floor(open), close)``."""

    def __init__(self, sessions: Sequence[Session]) -> None:
        self._starts = [floor_hour(s.open) for s in sessions]
        self._closes = [s.close for s in sessions]

    def index(self, ts: datetime) -> int | None:
        """Session index of a bar starting at ``ts``, or ``None`` outside every session."""
        i = bisect_right(self._starts, ts) - 1
        if i >= 0 and ts < self._closes[i]:
            return i
        return None

    def count(self, timestamps: Iterable[datetime]) -> int:
        """Number of timestamps that fall inside a session."""
        return sum(1 for ts in timestamps if self.index(ts) is not None)


@dataclass(frozen=True, slots=True)
class AlignedBar:
    """One hour present on both sides, inside a regular session."""

    ts: datetime
    session: int
    cap: float
    alp: float
    rel_spread: float


@dataclass(frozen=True, slots=True)
class Alignment:
    """Aligned bars plus each side's regular-session bar count (for diagnostics)."""

    bars: tuple[AlignedBar, ...]
    capital_bars: int
    alpaca_bars: int


def align(
    capital: Sequence[CapitalBar], alpaca: Sequence[AlpacaBar], locator: SessionLocator
) -> Alignment:
    """Inner-join both sides on identical UTC bar starts inside a regular session.

    Bars with a non-positive price on either side are dropped from the join.
    """
    cap_by_ts = {bar.ts: bar for bar in capital}
    alp_by_ts = {bar.ts: bar.close for bar in alpaca}
    aligned: list[AlignedBar] = []
    for ts in sorted(cap_by_ts.keys() & alp_by_ts.keys()):
        session = locator.index(ts)
        if session is None:
            continue
        cap_bar = cap_by_ts[ts]
        cap, alp = cap_bar.mid, alp_by_ts[ts]
        if cap > 0 and alp > 0:
            aligned.append(AlignedBar(ts, session, cap, alp, cap_bar.rel_spread))
    return Alignment(tuple(aligned), locator.count(cap_by_ts), locator.count(alp_by_ts))
