"""Response model of ``GET /api/v1/thresholds`` (``Thresholds`` in contracts/openapi.yaml)."""

from typing import Literal

from pydantic import BaseModel

from alpaca_gatherer.domain.thresholds import Thresholds

__all__ = [
    "BehaviorGroup",
    "CandidatesGroup",
    "PriceGroup",
    "ThresholdsResponse",
    "WindowGroup",
]


class CandidatesGroup(BaseModel):
    """Candidate generation."""

    name_ratio: float
    max_name_candidates: int


class WindowGroup(BaseModel):
    """Comparison window."""

    sessions: int
    embargo_minutes: int
    min_bars: int
    feed: Literal["sip", "iex"]


class PriceGroup(BaseModel):
    """Price check."""

    price_tol_pct: float
    spread_mult: float


class BehaviorGroup(BaseModel):
    """Behavior check."""

    corr_threshold: float
    dir_threshold: float
    min_sig_moves: int
    min_session_returns: int


class ThresholdsResponse(BaseModel):
    """Thresholds grouped by matching stage."""

    candidates: CandidatesGroup
    window: WindowGroup
    price: PriceGroup
    behavior: BehaviorGroup

    @classmethod
    def of(cls, t: Thresholds) -> ThresholdsResponse:
        """Build from the domain thresholds."""
        return cls.model_validate(t.as_dict())
