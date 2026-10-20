"""Read the thresholds in use (FR-007); they are fixed for the life of the process.

>>> GetThresholds(Thresholds.defaults())().window.sessions
20
"""

from alpaca_gatherer.domain.thresholds import Thresholds

__all__ = ["GetThresholds"]


class GetThresholds:
    """Return the threshold set loaded at startup."""

    def __init__(self, thresholds: Thresholds) -> None:
        self._thresholds = thresholds

    def __call__(self) -> Thresholds:
        """The thresholds, grouped by matching stage."""
        return self._thresholds
