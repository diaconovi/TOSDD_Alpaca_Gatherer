"""Data, price, behavior and tradability checks."""

import random

import pytest

from alpaca_gatherer.domain.mapping import FailedCheck, Horizon, ReasonCode
from alpaca_gatherer.domain.matching.checks import comovement, pearson, score_candidate
from alpaca_gatherer.domain.matching.window import SessionLocator
from alpaca_gatherer.domain.thresholds import Thresholds
from tests.builders import alpaca_bars, capital_bars, ref, session_hours, sessions, walk

TH = Thresholds.defaults()
SESSIONS = sessions(20)
LOCATOR = SessionLocator(SESSIONS)
TIMES = session_hours(SESSIONS)


def test_identical_prices_pass_at_hourly_horizon() -> None:
    mids = walk(len(TIMES))
    score = score_candidate(
        ref("X"), capital_bars(TIMES, mids), alpaca_bars(TIMES, mids), LOCATOR, 20, TH
    )
    assert score.passed
    assert score.horizon is Horizon.HOURLY
    assert score.price_diff_pct == 0.0
    assert score.price_tol_pct == pytest.approx(1.05)
    assert score.return_correlation == 1.0
    assert score.direction_agreement == 1.0
    assert score.aligned_bars == 140
    assert score.failed_check is None


def test_too_few_aligned_bars_reports_both_counts() -> None:
    short = sessions(5)
    times = session_hours(short)
    mids = walk(len(times))
    score = score_candidate(
        ref("X"),
        capital_bars(times, mids),
        alpaca_bars(times[:20], mids[:20]),
        SessionLocator(short),
        5,
        TH,
    )
    assert score.stage is ReasonCode.INSUFFICIENT_DATA
    assert score.failed_check is FailedCheck.DATA
    assert score.detail == (
        "only 20 aligned session bars (< 60); Capital.com has 35, Alpaca has 20 of ~35 possible"
    )


def test_no_alpaca_bars() -> None:
    mids = walk(len(TIMES))
    score = score_candidate(ref("X"), capital_bars(TIMES, mids), [], LOCATOR, 20, TH)
    assert score.stage is ReasonCode.INSUFFICIENT_DATA
    assert score.detail == "no Alpaca bars in window"


def test_price_diff_is_median_relative_difference() -> None:
    mids = walk(len(TIMES))
    score = score_candidate(
        ref("X"),
        capital_bars(TIMES, mids),
        alpaca_bars(TIMES, [m * 1.05 for m in mids]),
        LOCATOR,
        20,
        TH,
    )
    assert score.stage is ReasonCode.FAILED_PRICE_CHECK
    assert score.failed_check is FailedCheck.PRICE
    assert score.price_diff_pct == pytest.approx(4.7619, abs=1e-4)
    assert score.progress == 1


def test_tolerance_grows_with_capital_spread() -> None:
    mids = walk(len(TIMES))
    closes = [m / 1.015 for m in mids]  # 1.5 % apart
    tight = score_candidate(
        ref("X"), capital_bars(TIMES, mids, 0.1), alpaca_bars(TIMES, closes), LOCATOR, 20, TH
    )
    wide = score_candidate(
        ref("X"), capital_bars(TIMES, mids, 2.0), alpaca_bars(TIMES, closes), LOCATOR, 20, TH
    )
    assert tight.stage is ReasonCode.FAILED_PRICE_CHECK
    assert wide.price_tol_pct == pytest.approx(2.0)
    assert wide.price_ok
    assert wide.passed


def test_session_fallback_for_quiet_hourly_moves() -> None:
    rng = random.Random(7)
    levels = walk(len(SESSIONS), vol=0.02, seed=3)
    mids: list[float] = []
    closes: list[float] = []
    for i, level in enumerate(levels):
        for hour in range(7):
            last = hour == 6
            mids.append(level * (1 + (0 if last else rng.gauss(0, 0.006))))
            closes.append(level * (1 + (0 if last else rng.gauss(0, 0.006))))
        assert len(mids) == 7 * (i + 1)
    score = score_candidate(
        ref("X"), capital_bars(TIMES, mids, 1.0), alpaca_bars(TIMES, closes), LOCATOR, 20, TH
    )
    assert score.passed, score.detail
    assert score.horizon is Horizon.SESSION
    assert score.return_correlation == score.session_correlation == 1.0
    assert score.n_session_moves == 19


def test_unrelated_moves_fail_behavior() -> None:
    rng = random.Random(11)
    mids = [100 * (1 + rng.gauss(0, 0.003)) for _ in TIMES]
    closes = [100 * (1 + rng.gauss(0, 0.003)) for _ in TIMES]
    score = score_candidate(
        ref("X"), capital_bars(TIMES, mids), alpaca_bars(TIMES, closes), LOCATOR, 20, TH
    )
    assert score.price_ok
    assert score.stage is ReasonCode.FAILED_BEHAVIOR_CHECK
    assert score.failed_check is FailedCheck.BEHAVIOR
    assert score.horizon is Horizon.HOURLY
    assert "need dir>=0.75 and corr>=0.7" in score.detail
    assert score.progress == 3


def test_flat_prices_are_insufficient_data_not_behavior() -> None:
    flat = [50.0] * len(TIMES)
    score = score_candidate(
        ref("X"), capital_bars(TIMES, flat), alpaca_bars(TIMES, flat), LOCATOR, 20, TH
    )
    assert score.stage is ReasonCode.INSUFFICIENT_DATA
    assert (
        score.detail
        == "too few moves above the spread to judge co-movement (0 hourly, 0 session-close)"
    )
    assert score.price_ok
    assert score.progress == 2


@pytest.mark.parametrize(
    ("tradable", "active", "text"),
    [(False, True, "is active, tradable=False"), (True, False, "is inactive, tradable=True")],
)
def test_tradability_is_checked_last(tradable: bool, active: bool, text: str) -> None:
    mids = walk(len(TIMES))
    score = score_candidate(
        ref("X", tradable=tradable, active=active),
        capital_bars(TIMES, mids),
        alpaca_bars(TIMES, mids),
        LOCATOR,
        20,
        TH,
    )
    assert score.stage is ReasonCode.NOT_TRADABLE
    assert score.failed_check is FailedCheck.TRADABILITY
    assert text in score.detail
    assert score.return_correlation == 1.0
    assert score.progress == 4


def test_comovement_counts_only_significant_direction() -> None:
    closes = [(100.0, 100.0), (100.05, 99.97), (102.0, 102.0), (101.0, 101.0)]
    m = comovement(closes, noise=0.001)
    assert m.n == 3
    assert m.n_sig == 2  # the 0.05 % / -0.03 % pair is bid/ask bounce
    assert m.direction == 1.0


def test_pearson_degenerate_cases() -> None:
    assert pearson([1.0, 2.0], [1.0, 2.0]) is None
    assert pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
    assert pearson([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(-1.0)
