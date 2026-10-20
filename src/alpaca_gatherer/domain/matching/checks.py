"""Candidate checks, in order: data → price → behavior → tradability.

* **Data**: at least ``min_bars`` aligned regular-session bars.
* **Price** (sanity filter): median ``|cap_mid - alpaca_close| / alpaca_close * 100`` must be within
  ``price_tol_pct + spread_mult * median(cap_spread / cap_mid) * 100``.
* **Behavior** (decisive): log-return co-movement, first on hourly returns (direction counted only
  on moves larger than the Capital.com median relative spread), else on session-close returns.
* **Tradability** last, so a correct but untradable counterpart is reported as such.

>>> comovement([(100.0, 100.0), (101.0, 101.0), (100.0, 100.0), (102.0, 102.0)], 0.0)
CoMovement(n=3, n_sig=3, direction=1.0, corr=1.0)
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, replace
from itertools import pairwise

from alpaca_gatherer.domain.mapping import CandidateKind, FailedCheck, Horizon, ReasonCode
from alpaca_gatherer.domain.matching.candidates import CandidateRef
from alpaca_gatherer.domain.matching.models import AlpacaBar, CapitalBar
from alpaca_gatherer.domain.matching.window import AlignedBar, SessionLocator, align
from alpaca_gatherer.domain.thresholds import Thresholds

__all__ = [
    "CandidateScore",
    "CoMovement",
    "comovement",
    "no_data_score",
    "pearson",
    "score_candidate",
]

_FAILED_CHECK = {
    ReasonCode.INSUFFICIENT_DATA: FailedCheck.DATA,
    ReasonCode.FAILED_PRICE_CHECK: FailedCheck.PRICE,
    ReasonCode.FAILED_BEHAVIOR_CHECK: FailedCheck.BEHAVIOR,
    ReasonCode.NOT_TRADABLE: FailedCheck.TRADABILITY,
}
_BARS_PER_SESSION = 7


@dataclass(frozen=True, slots=True)
class CandidateScore:
    """Outcome of checking one candidate; ``stage`` is ``None`` when every check passed."""

    symbol: str
    kind: CandidateKind
    active: bool
    tradable: bool
    stage: ReasonCode | None = None
    detail: str = ""
    aligned_bars: int | None = None
    price_diff_pct: float | None = None
    price_tol_pct: float | None = None
    direction_agreement: float | None = None
    return_correlation: float | None = None
    horizon: Horizon | None = None
    n_sig_moves: int = 0
    n_session_moves: int = 0
    session_direction: float | None = None
    session_correlation: float | None = None

    @property
    def passed(self) -> bool:
        """True if every check passed."""
        return self.stage is None

    @property
    def failed_check(self) -> FailedCheck | None:
        """The check category that failed, if any."""
        return None if self.stage is None else _FAILED_CHECK.get(self.stage)

    @property
    def price_ok(self) -> bool:
        """True if the price check was reached and passed."""
        return (
            self.price_diff_pct is not None
            and self.price_tol_pct is not None
            and self.price_diff_pct <= self.price_tol_pct
        )

    @property
    def progress(self) -> int:
        """How far the candidate got (used to report the most informative failure)."""
        if self.passed or self.stage is ReasonCode.NOT_TRADABLE:
            return 4
        if self.stage is ReasonCode.FAILED_BEHAVIOR_CHECK:
            return 3
        if self.price_ok:  # passed price, then too quiet to judge behavior
            return 2
        return 1 if self.stage is ReasonCode.FAILED_PRICE_CHECK else 0


@dataclass(frozen=True, slots=True)
class CoMovement:
    """Return co-movement at one horizon."""

    n: int
    n_sig: int
    direction: float | None
    corr: float | None


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Pearson correlation, or ``None`` with fewer than 3 pairs or a constant series.

    >>> pearson([1, 2, 3], [2, 4, 7])
    0.9933992677987828
    """
    n = len(xs)
    if n <= 2:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return sxy / math.sqrt(sxx * syy)


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def comovement(closes: Sequence[tuple[float, float]], noise: float) -> CoMovement:
    """Co-movement of consecutive log returns of ``(capital, alpaca)`` closes.

    Correlation uses every return pair; direction agreement uses only pairs where both sides moved
    and at least one move exceeds ``noise``.
    """
    cap_r = [math.log(b[0]) - math.log(a[0]) for a, b in pairwise(closes)]
    alp_r = [math.log(b[1]) - math.log(a[1]) for a, b in pairwise(closes)]
    corr = pearson(cap_r, alp_r)
    sig = [
        (c, a)
        for c, a in zip(cap_r, alp_r, strict=True)
        if max(abs(c), abs(a)) > noise and c != 0 and a != 0
    ]
    direction = sum(_sign(c) == _sign(a) for c, a in sig) / len(sig) if sig else None
    return CoMovement(
        n=len(cap_r),
        n_sig=len(sig),
        direction=None if direction is None else round(direction, 4),
        corr=None if corr is None else round(corr, 4),
    )


def _session_closes(bars: Sequence[AlignedBar]) -> list[tuple[float, float]]:
    last: dict[int, AlignedBar] = {}
    for bar in bars:
        last[bar.session] = bar
    return [(last[i].cap, last[i].alp) for i in sorted(last)]


def no_data_score(ref: CandidateRef, detail: str) -> CandidateScore:
    """Score for a candidate that could not be compared (e.g. no Capital.com history)."""
    return CandidateScore(
        symbol=ref.symbol,
        kind=ref.kind,
        active=ref.asset.active,
        tradable=ref.asset.tradable,
        stage=ReasonCode.INSUFFICIENT_DATA,
        detail=detail,
    )


def score_candidate(
    ref: CandidateRef,
    capital: Sequence[CapitalBar],
    alpaca: Sequence[AlpacaBar] | None,
    locator: SessionLocator,
    n_sessions: int,
    th: Thresholds,
) -> CandidateScore:
    """Run the data, price, behavior and tradability checks for one candidate."""
    base = CandidateScore(
        symbol=ref.symbol, kind=ref.kind, active=ref.asset.active, tradable=ref.asset.tradable
    )
    if not alpaca:
        return replace(base, stage=ReasonCode.INSUFFICIENT_DATA, detail="no Alpaca bars in window")
    alignment = align(capital, alpaca, locator)
    bars = alignment.bars
    n_bars = len(bars)
    if n_bars < th.window.min_bars:
        return replace(
            base,
            stage=ReasonCode.INSUFFICIENT_DATA,
            aligned_bars=n_bars,
            detail=(
                f"only {n_bars} aligned session bars (< {th.window.min_bars}); "
                f"Capital.com has {alignment.capital_bars}, Alpaca has {alignment.alpaca_bars} "
                f"of ~{n_sessions * _BARS_PER_SESSION} possible"
            ),
        )

    rel = [abs(b.cap - b.alp) / b.alp * 100 for b in bars]
    noise = statistics.median(b.rel_spread for b in bars)
    price_diff = round(statistics.median(rel), 4)
    tolerance = round(th.price.price_tol_pct + th.price.spread_mult * noise * 100, 4)
    scored = replace(base, aligned_bars=n_bars, price_diff_pct=price_diff, price_tol_pct=tolerance)
    if price_diff > tolerance:
        return replace(
            scored,
            stage=ReasonCode.FAILED_PRICE_CHECK,
            detail=f"median price diff {price_diff:.3f}% > tolerance {tolerance:.3f}%",
        )

    hourly = comovement([(b.cap, b.alp) for b in bars], noise)
    session = comovement(_session_closes(bars), 0.0)
    scored = replace(
        scored,
        n_sig_moves=hourly.n_sig,
        n_session_moves=session.n_sig,
        session_direction=session.direction,
        session_correlation=session.corr,
    )
    b = th.behavior

    def ok(m: CoMovement, min_moves: int) -> bool:
        return (
            m.n_sig >= min_moves
            and m.corr is not None
            and m.corr >= b.corr_threshold
            and m.direction is not None
            and m.direction >= b.dir_threshold
        )

    if ok(hourly, b.min_sig_moves):
        scored = replace(
            scored,
            horizon=Horizon.HOURLY,
            direction_agreement=hourly.direction,
            return_correlation=hourly.corr,
        )
    elif ok(session, b.min_session_returns):
        scored = replace(
            scored,
            horizon=Horizon.SESSION,
            direction_agreement=session.direction,
            return_correlation=session.corr,
        )
    else:
        scored = replace(
            scored,
            horizon=Horizon.HOURLY,
            direction_agreement=hourly.direction,
            return_correlation=hourly.corr,
        )
        if hourly.n_sig < b.min_sig_moves and session.n_sig < b.min_session_returns:
            return replace(
                scored,
                stage=ReasonCode.INSUFFICIENT_DATA,
                detail=(
                    "too few moves above the spread to judge co-movement "
                    f"({hourly.n_sig} hourly, {session.n_sig} session-close)"
                ),
            )
        return replace(
            scored,
            stage=ReasonCode.FAILED_BEHAVIOR_CHECK,
            detail=(
                f"hourly dir {hourly.direction} corr {hourly.corr} (n_sig={hourly.n_sig}); "
                f"session dir {session.direction} corr {session.corr} (n_sig={session.n_sig}); "
                f"need dir>={b.dir_threshold} and corr>={b.corr_threshold}"
            ),
        )

    if not (ref.asset.tradable and ref.asset.active):
        status = "active" if ref.asset.active else "inactive"
        return replace(
            scored,
            stage=ReasonCode.NOT_TRADABLE,
            detail=f"Alpaca asset {ref.symbol} is {status}, tradable={ref.asset.tradable}",
        )
    return scored
