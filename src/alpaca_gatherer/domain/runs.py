"""Matching runs: states, transitions, counts and the history retention policy.

>>> started = datetime(2026, 10, 8, 6, tzinfo=UTC)
>>> run = Run.start("r1", RunTrigger.MANUAL, started, {})
>>> run.status, run.price_window_end == started
(<RunStatus.RUNNING: 'running'>, True)
>>> run.fail(started, RunError(RunErrorCode.INTERNAL_ERROR, "boom")).status
<RunStatus.FAILED: 'failed'>
"""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum

from alpaca_gatherer.domain.mapping import InstrumentMapping, MatchStatus
from alpaca_gatherer.domain.thresholds import ThresholdValue

__all__ = [
    "SKIP_HISTORY_LIMIT",
    "InvalidRunTransition",
    "Run",
    "RunCounts",
    "RunError",
    "RunErrorCode",
    "RunStatus",
    "RunTrigger",
    "RunWindow",
    "select_runs_to_prune",
]

SKIP_HISTORY_LIMIT = 20
"""Newest ``skipped_concurrent_run`` records kept, separately from executed runs."""


class RunStatus(StrEnum):
    """Run state; ``succeeded`` and ``failed`` are terminal."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunTrigger(StrEnum):
    """What started the run."""

    MANUAL = "manual"
    SCHEDULED = "scheduled"


class RunErrorCode(StrEnum):
    """Failure causes recorded on failed runs."""

    COLLECTOR_UNAVAILABLE = "collector_unavailable"
    COLLECTOR_INCOMPLETE_DATA = "collector_incomplete_data"
    ALPACA_UNAVAILABLE = "alpaca_unavailable"
    ALPACA_AUTH_FAILED = "alpaca_auth_failed"
    CREDENTIALS_MISSING = "credentials_missing"
    CREDENTIALS_UNDECRYPTABLE = "credentials_undecryptable"
    SKIPPED_CONCURRENT_RUN = "skipped_concurrent_run"
    INTERRUPTED_BY_RESTART = "interrupted_by_restart"
    INTERNAL_ERROR = "internal_error"


class InvalidRunTransition(ValueError):
    """A transition from a terminal state was attempted."""


@dataclass(frozen=True, slots=True)
class RunError:
    """Failure cause of a run."""

    code: RunErrorCode
    detail: str


@dataclass(frozen=True, slots=True)
class RunWindow:
    """The comparison window a run actually used."""

    start: datetime
    end: datetime
    sessions: int


@dataclass(frozen=True, slots=True)
class RunCounts:
    """Number of mapping records by status, plus non-matched records by reason code.

    >>> RunCounts(matched=2, ambiguous=0, unmatched=1, by_reason={"not_tradable": 1}).total
    3
    """

    matched: int
    ambiguous: int
    unmatched: int
    by_reason: Mapping[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        """Total number of mapping records."""
        return self.matched + self.ambiguous + self.unmatched

    @classmethod
    def of(cls, mappings: Iterable[InstrumentMapping]) -> RunCounts:
        """Count a list of mapping records."""
        statuses: Counter[MatchStatus] = Counter()
        reasons: Counter[str] = Counter()
        for m in mappings:
            statuses[m.status] += 1
            if m.reason is not None:
                reasons[m.reason.code.value] += 1
        return cls(
            matched=statuses[MatchStatus.MATCHED],
            ambiguous=statuses[MatchStatus.AMBIGUOUS],
            unmatched=statuses[MatchStatus.UNMATCHED],
            by_reason=dict(sorted(reasons.items())),
        )


@dataclass(frozen=True, slots=True)
class Run:
    """One execution (or recorded skip) of the matching process."""

    run_id: str
    trigger: RunTrigger
    status: RunStatus
    started_at: datetime
    price_window_end: datetime
    thresholds: Mapping[str, Mapping[str, ThresholdValue]]
    finished_at: datetime | None = None
    window: RunWindow | None = None
    counts: RunCounts | None = None
    error: RunError | None = None

    @classmethod
    def start(
        cls,
        run_id: str,
        trigger: RunTrigger,
        started_at: datetime,
        thresholds: Mapping[str, Mapping[str, ThresholdValue]],
    ) -> Run:
        """Create a ``running`` run whose price window ends at its start time (FR-008)."""
        started = started_at.astimezone(UTC)
        return cls(
            run_id=run_id,
            trigger=trigger,
            status=RunStatus.RUNNING,
            started_at=started,
            price_window_end=started,
            thresholds=thresholds,
        )

    @classmethod
    def skipped(
        cls,
        run_id: str,
        at: datetime,
        thresholds: Mapping[str, Mapping[str, ThresholdValue]],
        error: RunError,
    ) -> Run:
        """Create a terminal ``failed`` record for a scheduled trigger that could not execute."""
        return replace(
            cls.start(run_id, RunTrigger.SCHEDULED, at, thresholds),
            status=RunStatus.FAILED,
            finished_at=at.astimezone(UTC),
            error=error,
        )

    @property
    def is_terminal(self) -> bool:
        """True once the run has succeeded or failed."""
        return self.status is not RunStatus.RUNNING

    @property
    def is_skip_record(self) -> bool:
        """True for a recorded scheduled skip (kept in its own retention pool)."""
        return self.error is not None and self.error.code is RunErrorCode.SKIPPED_CONCURRENT_RUN

    def succeed(self, finished_at: datetime, counts: RunCounts, window: RunWindow) -> Run:
        """Return this run as ``succeeded``; only a running run may succeed."""
        self._require_running()
        return replace(
            self,
            status=RunStatus.SUCCEEDED,
            finished_at=finished_at.astimezone(UTC),
            counts=counts,
            window=window,
        )

    def fail(self, finished_at: datetime, error: RunError, window: RunWindow | None = None) -> Run:
        """Return this run as ``failed``; only a running run may fail."""
        self._require_running()
        return replace(
            self,
            status=RunStatus.FAILED,
            finished_at=finished_at.astimezone(UTC),
            error=error,
            window=window or self.window,
        )

    def _require_running(self) -> None:
        if self.is_terminal:
            raise InvalidRunTransition(f"run {self.run_id} is already {self.status}")


def select_runs_to_prune(
    runs: Sequence[Run], limit: int, skip_limit: int = SKIP_HISTORY_LIMIT
) -> list[str]:
    """Return the ids of runs to delete under the retention policy.

    Executed terminal runs beyond the newest ``limit`` and skip records beyond the newest
    ``skip_limit`` are selected; running runs never are.

    >>> t = datetime(2026, 1, 1, tzinfo=UTC)
    >>> runs = [Run.start(str(i), RunTrigger.MANUAL, t.replace(day=i + 1), {}) for i in range(3)]
    >>> done = [r.fail(r.started_at, RunError(RunErrorCode.INTERNAL_ERROR, "x")) for r in runs]
    >>> select_runs_to_prune(done, limit=2)
    ['0']
    """
    newest_first = sorted(runs, key=lambda r: r.started_at, reverse=True)
    executed = [r for r in newest_first if r.is_terminal and not r.is_skip_record]
    skips = [r for r in newest_first if r.is_terminal and r.is_skip_record]
    return [r.run_id for r in executed[limit:]] + [r.run_id for r in skips[skip_limit:]]
