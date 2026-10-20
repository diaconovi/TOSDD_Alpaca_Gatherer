"""Matching thresholds, grouped by the matching stage that uses them.

The values come from the threshold file loaded at startup and never change while the service runs.

>>> t = Thresholds.defaults()
>>> t.price.price_tol_pct
1.0
>>> t.as_dict()["window"]["feed"]
'sip'
"""

from dataclasses import asdict, dataclass
from typing import Literal

__all__ = [
    "BehaviorThresholds",
    "CandidateThresholds",
    "Feed",
    "PriceThresholds",
    "ThresholdValue",
    "Thresholds",
    "WindowThresholds",
]

type Feed = Literal["sip", "iex"]
type ThresholdValue = float | int | str


@dataclass(frozen=True, slots=True)
class CandidateThresholds:
    """Candidate generation: company-name fallback settings."""

    name_ratio: float
    max_name_candidates: int


@dataclass(frozen=True, slots=True)
class WindowThresholds:
    """Comparison window: sessions, embargo, minimum aligned bars and Alpaca feed."""

    sessions: int
    embargo_minutes: int
    min_bars: int
    feed: Feed


@dataclass(frozen=True, slots=True)
class PriceThresholds:
    """Price sanity check: base tolerance plus a spread-dependent allowance."""

    price_tol_pct: float
    spread_mult: float


@dataclass(frozen=True, slots=True)
class BehaviorThresholds:
    """Bar co-movement check at the hourly and session-close horizons."""

    corr_threshold: float
    dir_threshold: float
    min_sig_moves: int
    min_session_returns: int


@dataclass(frozen=True, slots=True)
class Thresholds:
    """The full, immutable threshold set used by a matching run."""

    candidates: CandidateThresholds
    window: WindowThresholds
    price: PriceThresholds
    behavior: BehaviorThresholds

    @classmethod
    def defaults(cls) -> Thresholds:
        """Return the reference defaults (the values shipped in ``config/thresholds.yaml``)."""
        return cls(
            candidates=CandidateThresholds(name_ratio=0.90, max_name_candidates=3),
            window=WindowThresholds(sessions=20, embargo_minutes=20, min_bars=60, feed="sip"),
            price=PriceThresholds(price_tol_pct=1.0, spread_mult=0.5),
            behavior=BehaviorThresholds(
                corr_threshold=0.70, dir_threshold=0.75, min_sig_moves=10, min_session_returns=12
            ),
        )

    def as_dict(self) -> dict[str, dict[str, ThresholdValue]]:
        """Return the thresholds as nested plain dictionaries (for run snapshots and responses)."""
        return {name: dict(group) for name, group in asdict(self).items()}
