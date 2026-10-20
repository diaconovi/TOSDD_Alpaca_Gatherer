"""System clock adapter.

>>> SystemClock().now().tzinfo
datetime.timezone.utc
"""

from datetime import UTC, datetime

__all__ = ["SystemClock"]


class SystemClock:
    """Returns the current wall-clock time in UTC."""

    def now(self) -> datetime:
        """Return the current time as an aware UTC datetime."""
        return datetime.now(UTC)
