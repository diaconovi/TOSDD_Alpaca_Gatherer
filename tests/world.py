"""A small, consistent fake market used by run tests: three US shares that all match."""

from dataclasses import dataclass
from datetime import date

from alpaca_gatherer.domain.mapping import Source
from alpaca_gatherer.domain.matching.models import CapitalHistory, CapitalInstrument
from tests.builders import (
    US_HOURS,
    alpaca_bars,
    asset,
    capital_bars,
    instrument,
    session_hours,
    sessions,
    walk,
)
from tests.fakes import FakeAlpaca, FakeCollector


@dataclass
class World:
    collector: FakeCollector
    alpaca: FakeAlpaca


EXPECTED = {
    "TSLA": ("matched", "exact", "TSLA"),
    "BRKB": ("matched", "alias", "BRK.B"),
    "CARR": ("matched", "exact", "CARR"),
    "SPX500": None,  # not a share: never in the universe
}


def build_world(n_sessions: int = 20, start: date | None = None) -> World:
    window = sessions(n_sessions, start) if start else sessions(n_sessions)
    times = session_hours(window)
    prices = {
        "TSLA": walk(len(times), 430, seed=1),
        "BRK.B": walk(len(times), 470, seed=2),
        "CARR": walk(len(times), 60, seed=3),
    }
    catalog = [
        instrument("TSLA", name="Tesla Inc"),
        instrument("BRKB", "BRKb", "Berkshire Hathaway Inc - B"),
        CapitalInstrument("SPX500", "SPX500", "US 500", "INDICES", Source.CATALOG),
    ]
    swept = CapitalInstrument(
        "CARR", "CARR", "Carrier Global Corp", "SHARES", Source.SWEEP, "USD", US_HOURS
    )
    collector = FakeCollector(
        catalog=catalog,
        markets={"CARR": swept},
        histories={
            "TSLA": CapitalHistory(capital_bars(times, prices["TSLA"])),
            "BRKB": CapitalHistory(capital_bars(times, prices["BRK.B"])),
            "CARR": CapitalHistory(capital_bars(times, prices["CARR"])),
        },
    )
    alpaca = FakeAlpaca(
        assets=[
            asset("TSLA", "Tesla, Inc. Common Stock"),
            asset("BRK.B", "Berkshire Hathaway Inc. Class B"),
            asset("CARR", "Carrier Global Corporation"),
            asset("CHSN", "Chanson International Holding", tradable=False),
        ],
        sessions=window,
        bars={symbol: alpaca_bars(times, p) for symbol, p in prices.items()},
    )
    return World(collector, alpaca)
