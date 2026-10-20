"""Run transitions, counts and the retention policy (data-model.md §2)."""

from datetime import UTC, datetime, timedelta

import pytest

from alpaca_gatherer.domain.runs import (
    InvalidRunTransition,
    Run,
    RunCounts,
    RunError,
    RunErrorCode,
    RunStatus,
    RunTrigger,
    RunWindow,
    select_runs_to_prune,
)
from tests.samples import ambiguous, matched, unmatched

T0 = datetime(2026, 10, 1, tzinfo=UTC)
ERROR = RunError(RunErrorCode.COLLECTOR_UNAVAILABLE, "down")
WINDOW = RunWindow(T0 - timedelta(days=28), T0, 20)


def started(i: int = 0, trigger: RunTrigger = RunTrigger.MANUAL) -> Run:
    return Run.start(f"r{i:03d}", trigger, T0 + timedelta(hours=i), {"price": {"x": 1}})


def test_start_sets_window_end_to_start_time() -> None:
    run = started()
    assert run.status is RunStatus.RUNNING
    assert run.price_window_end == run.started_at
    assert run.finished_at is None
    assert not run.is_terminal


def test_running_can_succeed_or_fail() -> None:
    counts = RunCounts(1, 0, 0)
    done = started().succeed(T0 + timedelta(minutes=20), counts, WINDOW)
    assert (done.status, done.counts, done.window) == (RunStatus.SUCCEEDED, counts, WINDOW)
    failed = started().fail(T0, ERROR)
    assert (failed.status, failed.error) == (RunStatus.FAILED, ERROR)
    assert failed.is_terminal


@pytest.mark.parametrize("terminal", ["succeeded", "failed"])
def test_terminal_states_are_final(terminal: str) -> None:
    run = started()
    done = (
        run.succeed(T0, RunCounts(0, 0, 0), WINDOW)
        if terminal == "succeeded"
        else run.fail(T0, ERROR)
    )
    with pytest.raises(InvalidRunTransition):
        done.fail(T0, ERROR)
    with pytest.raises(InvalidRunTransition):
        done.succeed(T0, RunCounts(0, 0, 0), WINDOW)


def test_skipped_record() -> None:
    skip = Run.skipped(
        "s1", T0, {}, RunError(RunErrorCode.SKIPPED_CONCURRENT_RUN, "run r1 was running")
    )
    assert skip.trigger is RunTrigger.SCHEDULED
    assert skip.status is RunStatus.FAILED
    assert skip.is_skip_record
    assert skip.finished_at == T0


def test_counts_of_mappings() -> None:
    counts = RunCounts.of([matched(), matched("TSLA", "TSLA"), unmatched(), ambiguous()])
    assert (counts.matched, counts.ambiguous, counts.unmatched, counts.total) == (2, 1, 1, 4)
    assert counts.by_reason == {"multiple_candidates": 1, "not_listed_on_alpaca": 1}


def test_retention_keeps_newest_executed_and_skips_separately() -> None:
    executed = [started(i).fail(T0, ERROR) for i in range(55)]
    skips = [
        Run.skipped(
            f"s{i:03d}",
            T0 + timedelta(hours=i),
            {},
            RunError(RunErrorCode.SKIPPED_CONCURRENT_RUN, "x"),
        )
        for i in range(25)
    ]
    running = started(100)
    doomed = set(select_runs_to_prune([*executed, *skips, running], limit=50, skip_limit=20))
    assert doomed == {f"r{i:03d}" for i in range(5)} | {f"s{i:03d}" for i in range(5)}
    assert running.run_id not in doomed


def test_skips_never_evict_executed_runs() -> None:
    executed = [started(i).fail(T0, ERROR) for i in range(50)]
    skips = [
        Run.skipped(
            f"s{i:03d}",
            T0 + timedelta(days=10, hours=i),
            {},
            RunError(RunErrorCode.SKIPPED_CONCURRENT_RUN, "x"),
        )
        for i in range(30)
    ]
    doomed = select_runs_to_prune([*executed, *skips], limit=50)
    assert doomed == [f"s{i:03d}" for i in range(9, -1, -1)]
