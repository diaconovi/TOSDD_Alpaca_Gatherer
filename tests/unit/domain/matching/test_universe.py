"""Universe filtering and merging (catalog plus sweep)."""

from alpaca_gatherer.domain.mapping import Source
from alpaca_gatherer.domain.matching.models import AlpacaAsset, CapitalInstrument, OpeningHours
from alpaca_gatherer.domain.matching.universe import (
    build_universe,
    keep_swept,
    sweep_candidates,
    trades_us_session,
)

US_HOURS = OpeningHours("UTC", {"mon": ("13:30 - 20:00",), "fri": ("13:30 - 20:00",)})


def inst(
    epic: str,
    source: Source = Source.CATALOG,
    kind: str = "SHARES",
    currency: str | None = "USD",
    hours: OpeningHours | None = US_HOURS,
) -> CapitalInstrument:
    return CapitalInstrument(
        epic=epic,
        symbol=epic,
        name=f"{epic} Inc",
        instrument_type=kind,
        source=source,
        currency=currency,
        opening_hours=hours,
    )


def test_catalog_keeps_only_shares_regardless_of_currency_and_hours() -> None:
    universe = build_universe(
        [inst("TSLA"), inst("SPX500", kind="INDICES"), inst("BKT", currency="EUR", hours=None)], []
    )
    assert [i.epic for i in universe] == ["BKT", "TSLA"]


def test_swept_needs_shares_usd_and_us_hours() -> None:
    swept = [
        inst("ALL", Source.SWEEP),
        inst("BKT", Source.SWEEP, currency="EUR"),
        inst("CSC", Source.SWEEP, hours=OpeningHours("UTC", {"mon": ("00:00 - 06:00",)})),
        inst("GLD", Source.SWEEP, kind="COMMODITIES"),
    ]
    assert [i.epic for i in build_universe([], swept)] == ["ALL"]


def test_catalog_takes_precedence_over_sweep() -> None:
    universe = build_universe(
        [inst("TSLA")], [inst("TSLA", Source.SWEEP), inst("CARR", Source.SWEEP)]
    )
    assert [(i.epic, i.source) for i in universe] == [
        ("CARR", Source.SWEEP),
        ("TSLA", Source.CATALOG),
    ]


def test_duplicate_catalog_entries_merge_to_one() -> None:
    assert len(build_universe([inst("TSLA"), inst("TSLA")], [])) == 1


def test_us_session_hours() -> None:
    assert trades_us_session(OpeningHours("UTC", {"tue": ("14:30 - 21:00",)}))
    assert trades_us_session(OpeningHours("UTC", {"wed": ("00:15 - 00:00",)}))  # 24 h
    assert not trades_us_session(OpeningHours("UTC", {"sat": ("13:30 - 20:00",)}))
    assert not trades_us_session(OpeningHours("Europe/London", {"mon": ("13:30 - 20:00",)}))
    assert not trades_us_session(None)


def test_keep_swept() -> None:
    assert keep_swept(inst("ALL", Source.SWEEP))
    assert not keep_swept(inst("ALL", Source.SWEEP, currency=None))


def test_sweep_candidates_from_active_symbols_minus_known() -> None:
    assets = [
        AlpacaAsset("BRK.B", "Berkshire", "NYSE", active=True, tradable=True),
        AlpacaAsset("OLD", "Old Co", "NYSE", active=False, tradable=False),
        AlpacaAsset("TSLA", "Tesla", "NASDAQ", active=True, tradable=True),
    ]
    assert sweep_candidates(assets, {"TSLA"}) == ["BRKB", "BRKBUS", "TSLAUS"]
