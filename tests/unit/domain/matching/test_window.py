"""Window selection, regular-session filtering and alignment."""

from datetime import UTC, date, datetime, timedelta

import pytest

from alpaca_gatherer.domain.errors import AlpacaUnavailable
from alpaca_gatherer.domain.matching.models import AlpacaBar, CapitalBar, Session
from alpaca_gatherer.domain.matching.window import (
    SessionLocator,
    align,
    calendar_range,
    floor_hour,
    query_range,
    select_sessions,
)
from tests.builders import sessions


def at(day: int, hour: int, minute: int = 0, month: int = 10) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def test_selects_last_complete_sessions_with_embargo() -> None:
    cal = sessions(10, date(2026, 9, 28))  # 2026-09-28 … 2026-10-09
    end = at(9, 20, 15)  # 15 min after the 2026-10-09 close
    chosen = select_sessions(cal, end, count=3, embargo_minutes=20)
    assert [s.open.date() for s in chosen] == [
        date(2026, 10, 6),
        date(2026, 10, 7),
        date(2026, 10, 8),
    ]
    chosen = select_sessions(cal, at(9, 20, 20), count=3, embargo_minutes=20)
    assert chosen[-1].open.date() == date(2026, 10, 9)


def test_unsorted_calendar_is_sorted() -> None:
    cal = list(reversed(sessions(4)))
    chosen = select_sessions(cal, at(30, 0), count=2, embargo_minutes=0)
    assert chosen[0].open < chosen[1].open


def test_not_enough_sessions_is_an_alpaca_error() -> None:
    with pytest.raises(AlpacaUnavailable, match="2 complete sessions; 5"):
        select_sessions(sessions(2), at(30, 0), count=5, embargo_minutes=20)


def test_query_range_floors_first_open() -> None:
    chosen = sessions(3)
    start, end = query_range(chosen)
    assert start == floor_hour(chosen[0].open) == chosen[0].open.replace(minute=0)
    assert end == chosen[-1].close


def test_calendar_range_covers_enough_days() -> None:
    assert calendar_range(at(8, 6), 20) == (date(2026, 8, 19), date(2026, 10, 8))


def test_regular_session_membership_half_day_and_dst() -> None:
    summer = Session(at(30, 13, 30, month=10), at(30, 20, 0, month=10))
    half_day = Session(
        datetime(2026, 11, 27, 14, 30, tzinfo=UTC), datetime(2026, 11, 27, 18, 0, tzinfo=UTC)
    )
    winter = Session(
        datetime(2026, 11, 30, 14, 30, tzinfo=UTC), datetime(2026, 11, 30, 21, 0, tzinfo=UTC)
    )
    locator = SessionLocator([summer, half_day, winter])
    assert locator.index(at(30, 13, month=10)) == 0  # floor(13:30) = 13:00 is included
    assert locator.index(at(30, 19, month=10)) == 0
    assert locator.index(at(30, 20, month=10)) is None  # close is excluded
    assert locator.index(datetime(2026, 11, 27, 17, tzinfo=UTC)) == 1
    assert locator.index(datetime(2026, 11, 27, 18, tzinfo=UTC)) is None  # half day ends at 18:00
    assert locator.index(datetime(2026, 11, 30, 13, tzinfo=UTC)) is None  # winter opens 14:30
    assert locator.index(datetime(2026, 11, 30, 20, tzinfo=UTC)) == 2
    assert locator.index(at(29, 15, month=10)) is None  # not a session day
    assert locator.count([at(30, 13, month=10), at(30, 22, month=10)]) == 1


def test_align_inner_joins_on_identical_timestamps_inside_sessions() -> None:
    session = Session(at(7, 13, 30), at(7, 20))
    locator = SessionLocator([session])
    capital = [
        CapitalBar(at(7, 12), 99.0, 101.0),  # pre-market: dropped
        CapitalBar(at(7, 13), 99.0, 101.0),
        CapitalBar(at(7, 14), 99.0, 101.0),  # no Alpaca bar at 14:00
        CapitalBar(at(7, 15), 0.0, 0.0),  # non-positive mid: dropped
        CapitalBar(at(7, 16), 99.0, 101.0),
    ]
    alpaca = [
        AlpacaBar(at(7, 12), 100.0),
        AlpacaBar(at(7, 13), 100.5),
        AlpacaBar(at(7, 15), 100.0),
        AlpacaBar(at(7, 16), 100.2),
        AlpacaBar(at(7, 16, 30), 100.2),  # not on the hour: no Capital.com match
    ]
    alignment = align(capital, alpaca, locator)
    assert [b.ts for b in alignment.bars] == [at(7, 13), at(7, 16)]
    assert alignment.bars[0].cap == 100.0
    assert alignment.bars[0].alp == 100.5
    assert alignment.bars[0].rel_spread == pytest.approx(0.02)
    assert alignment.capital_bars == 4
    assert alignment.alpaca_bars == 4


def test_sessions_must_be_aware_and_ordered() -> None:
    with pytest.raises(ValueError, match="aware"):
        Session(datetime(2026, 1, 1, 13), datetime(2026, 1, 1, 20))
    with pytest.raises(ValueError, match="after"):
        Session(at(1, 20), at(1, 13))
    assert at(1, 0) + timedelta(hours=1) == at(1, 1)
