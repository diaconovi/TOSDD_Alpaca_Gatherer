"""The pure pipeline: plan, name fallback gate and full classification."""

import random
from datetime import UTC, datetime

from alpaca_gatherer.domain.mapping import MatchStatus, MatchType, ReasonCode
from alpaca_gatherer.domain.matching.models import AlpacaBar, CapitalHistory
from alpaca_gatherer.domain.matching.pipeline import (
    build_plan,
    match_universe,
    name_candidates_needed,
)
from alpaca_gatherer.domain.thresholds import Thresholds
from tests.builders import (
    alpaca_bars,
    asset,
    capital_bars,
    instrument,
    session_hours,
    sessions,
    walk,
)

TH = Thresholds.defaults()
SESSIONS = sessions(20)
TIMES = session_hours(SESSIONS)
NOW = datetime(2026, 10, 18, tzinfo=UTC)


def noisy(base: list[float], seed: int) -> list[float]:
    rng = random.Random(seed)
    return [p * (1 + rng.gauss(0, 0.003)) for p in [100.0] * len(base)]


def test_full_pipeline() -> None:
    tsla = walk(len(TIMES), seed=1)
    ball = walk(len(TIMES), 90, seed=2)
    ibhi_cap = noisy(tsla, 3)
    universe = [
        instrument("TSLA", name="Tesla Inc"),
        instrument("BLL", name="Ball Corp"),
        instrument("IBHI", name="iShares iBonds 2029 Term High Yield"),
        instrument("NONE", name="Nothing Like It"),
        instrument("BIL", name="SPDR Bloomberg T-Bill"),
    ]
    assets = [
        asset("TSLA", "Tesla, Inc. Common Stock"),
        asset("BALL", "Ball Corporation"),
        asset("IBHI", "iShares iBonds 2029 Term High Yield and Income ETF"),
        asset("IBHH", "iShares iBonds 2028 Term High Yield and Income ETF"),
        asset("BIL", "SPDR Bloomberg 1-3 Month T-Bill ETF"),
    ]
    plan = build_plan(universe, assets, TH)
    assert sorted(plan.epics_needing_history()) == ["BIL", "BLL", "IBHI", "TSLA"]
    assert plan.symbols() == {"TSLA", "BALL", "IBHI", "BIL"}

    histories = {
        "TSLA": CapitalHistory(capital_bars(TIMES, tsla)),
        "BLL": CapitalHistory(capital_bars(TIMES, ball)),
        "IBHI": CapitalHistory(capital_bars(TIMES, ibhi_cap)),
        "BIL": CapitalHistory.missing(
            "Capital.com has no HOUR price history for this epic (HTTP 404)"
        ),
    }
    bars: dict[str, list[AlpacaBar]] = {
        "TSLA": alpaca_bars(TIMES, tsla),
        "BALL": alpaca_bars(TIMES, ball),
        "IBHI": alpaca_bars(TIMES, noisy(tsla, 4)),  # same price level, unrelated moves
        "IBHH": alpaca_bars(TIMES, ibhi_cap),  # a sibling that would pass if it were checked
    }
    # IBHI's own exact symbol passed price (behavior failed): no name fallback, so IBHH is not
    # requested. BALL (BLL's name candidate) is returned; the caller skips symbols it already has.
    assert name_candidates_needed(plan, histories, bars, SESSIONS) == {"BALL"}

    records = {
        r.capital_epic: r
        for r in match_universe(plan, histories, bars, SESSIONS, run_id="r1", produced_at=NOW)
    }
    assert (records["TSLA"].status, records["TSLA"].match_type) == (
        MatchStatus.MATCHED,
        MatchType.EXACT,
    )
    assert (records["BLL"].alpaca_symbol, records["BLL"].match_type) == ("BALL", MatchType.ALIAS)
    ibhi = records["IBHI"]
    assert ibhi.reason is not None
    assert ibhi.reason.code is ReasonCode.FAILED_BEHAVIOR_CHECK
    assert [c.alpaca_symbol for c in ibhi.candidates] == ["IBHI"]
    none = records["NONE"]
    assert none.reason is not None
    assert none.reason.code is ReasonCode.NOT_LISTED_ON_ALPACA
    bil = records["BIL"]
    assert bil.reason is not None
    assert bil.reason.code is ReasonCode.INSUFFICIENT_DATA
    assert "HTTP 404" in bil.reason.detail
    assert all(r.run_id == "r1" and r.updated_at == NOW for r in records.values())


def test_name_candidates_needed_when_identifier_fails_price() -> None:
    prices = walk(len(TIMES), seed=5)
    universe = [instrument("BAM", name="Brookfield Corp")]
    assets = [asset("BAM", "Brookfield Asset Management"), asset("BN", "Brookfield Corporation")]
    plan = build_plan(universe, assets, TH)
    histories = {"BAM": CapitalHistory(capital_bars(TIMES, prices))}
    bars = {"BAM": alpaca_bars(TIMES, [p * 1.4 for p in prices])}
    assert name_candidates_needed(plan, histories, bars, SESSIONS) == {"BN"}
    bars["BN"] = alpaca_bars(TIMES, prices)
    (record,) = match_universe(plan, histories, bars, SESSIONS, run_id="r", produced_at=NOW)
    assert (record.status, record.alpaca_symbol, record.match_type) == (
        MatchStatus.MATCHED,
        "BN",
        MatchType.ALIAS,
    )


def test_missing_history_is_insufficient_data() -> None:
    plan = build_plan([instrument("TSLA")], [asset("TSLA")], TH)
    (record,) = match_universe(plan, {}, {}, SESSIONS, run_id="r", produced_at=NOW)
    assert record.reason is not None
    assert record.reason.detail == "Capital.com returned no bars in window"
