"""Run use cases with fakes: start, execute, failures, pruning and logging."""

import asyncio
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from alpaca_gatherer.application.credentials import CredentialsProvider
from alpaca_gatherer.application.runs.execute_run import ExecuteRun
from alpaca_gatherer.application.runs.queries import GetRun, ListRuns
from alpaca_gatherer.application.runs.start_run import StartRun
from alpaca_gatherer.domain.credentials import EncryptedCredentials
from alpaca_gatherer.domain.errors import (
    AlpacaAuthFailed,
    CollectorIncompleteData,
    CollectorUnavailable,
    CredentialsMissing,
    RunInProgress,
    RunNotFound,
)
from alpaca_gatherer.domain.mapping import MatchStatus
from alpaca_gatherer.domain.runs import Run, RunError, RunErrorCode, RunStatus, RunTrigger
from alpaca_gatherer.domain.thresholds import Thresholds
from alpaca_gatherer.logging_setup import current_run_id, reset_secrets
from tests.fakes import (
    FrozenClock,
    InMemoryCredentialRepository,
    InMemoryMappingRepository,
    InMemoryRunRepository,
    ReversingCipher,
)
from tests.samples import matched
from tests.world import EXPECTED, World, build_world

T0 = datetime(2026, 10, 18, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_secrets() -> Iterator[None]:
    yield
    reset_secrets()


@dataclass
class Harness:
    world: World
    clock: FrozenClock
    creds: InMemoryCredentialRepository
    mappings: InMemoryMappingRepository
    runs: InMemoryRunRepository
    execute: ExecuteRun
    start: StartRun

    async def run_to_end(self, trigger: RunTrigger = RunTrigger.MANUAL) -> Run:
        run = await self.start(trigger)
        task = self.start.active_task
        assert task is not None
        await task
        final = await self.runs.get(run.run_id)
        assert final is not None
        return final


def registered() -> EncryptedCredentials:
    cipher = ReversingCipher()
    return EncryptedCredentials(cipher.encrypt("KEY-1234"), cipher.encrypt("SECRET-5678"), T0, T0)


def make(creds: EncryptedCredentials | None = None, live: bool = False) -> Harness:
    world = build_world()
    clock = FrozenClock(T0)
    creds_repo = InMemoryCredentialRepository(creds)
    mappings = InMemoryMappingRepository([matched(run_id="old")] if live else [])
    runs = InMemoryRunRepository()
    provider = CredentialsProvider(creds_repo, ReversingCipher())
    thresholds = Thresholds.defaults()
    execute = ExecuteRun(
        credentials=provider,
        collector=world.collector,
        alpaca=world.alpaca,
        mappings=mappings,
        runs=runs,
        clock=clock,
        thresholds=thresholds,
        history_limit=50,
    )
    start = StartRun(
        credentials=provider,
        runs=runs,
        execute=execute,
        clock=clock,
        thresholds=thresholds,
        history_limit=50,
    )
    return Harness(world, clock, creds_repo, mappings, runs, execute, start)


async def test_start_without_credentials_is_rejected() -> None:
    h = make()
    with pytest.raises(CredentialsMissing):
        await h.start()
    assert await h.runs.count() == 0


async def test_successful_run_swaps_mapping_and_records_counts() -> None:
    h = make(registered())
    run = await h.run_to_end()
    assert run.status is RunStatus.SUCCEEDED
    assert run.price_window_end == run.started_at == T0
    assert run.finished_at == T0
    assert run.counts is not None
    assert (run.counts.matched, run.counts.ambiguous, run.counts.unmatched) == (3, 0, 0)
    assert run.counts.total == 3
    assert run.counts.by_reason == {}
    assert run.window is not None
    assert run.window.sessions == 20
    assert run.thresholds == Thresholds.defaults().as_dict()
    assert h.mappings.swapped == [run.run_id]
    assert h.mappings.staging == {}
    live = h.mappings.live or {}
    for epic, expected in EXPECTED.items():
        if expected is None:
            assert epic not in live
            continue
        record = live[epic]
        assert (
            record.status.value,
            record.match_type and record.match_type.value,
            record.alpaca_symbol,
        ) == expected
        assert record.run_id == run.run_id
        assert record.updated_at == run.finished_at
    assert h.world.alpaca.seen_credentials[0].api_key == "KEY-1234"


async def test_second_start_while_running_is_rejected() -> None:
    h = make(registered())
    gate = asyncio.Event()
    h.world.collector.gate = gate
    first = await h.start()
    with pytest.raises(RunInProgress) as info:
        await h.start()
    assert info.value.active_run_id == first.run_id
    gate.set()
    task = h.start.active_task
    assert task is not None
    await task


async def test_scheduled_collision_is_recorded_as_skip() -> None:
    h = make(registered())
    await h.runs.insert_running(Run.start("busy", RunTrigger.MANUAL, T0, {}))
    skip = await h.start(RunTrigger.SCHEDULED)
    assert skip.status is RunStatus.FAILED
    assert skip.error is not None
    assert skip.error.code is RunErrorCode.SKIPPED_CONCURRENT_RUN
    assert "busy" in skip.error.detail
    assert await h.runs.get(skip.run_id) == skip


async def test_scheduled_without_credentials_is_recorded() -> None:
    h = make()
    run = await h.start(RunTrigger.SCHEDULED)
    assert run.error is not None
    assert run.error.code is RunErrorCode.CREDENTIALS_MISSING


@pytest.mark.parametrize(
    ("where", "error", "code"),
    [
        (
            "collector",
            CollectorUnavailable("prices AAPL: down"),
            RunErrorCode.COLLECTOR_UNAVAILABLE,
        ),
        (
            "collector",
            CollectorIncompleteData("no catalogs"),
            RunErrorCode.COLLECTOR_INCOMPLETE_DATA,
        ),
        ("alpaca", AlpacaAuthFailed(), RunErrorCode.ALPACA_AUTH_FAILED),
        ("alpaca", RuntimeError("boom"), RunErrorCode.INTERNAL_ERROR),
    ],
)
async def test_failures_keep_live_mapping(where: str, error: Exception, code: RunErrorCode) -> None:
    h = make(registered(), live=True)
    before = dict(h.mappings.live or {})
    if where == "collector":
        h.world.collector.fail_with = error
    else:
        h.world.alpaca.fail_with = error
    run = await h.run_to_end()
    assert run.status is RunStatus.FAILED
    assert run.error is not None
    assert run.error.code is code
    assert "boom" not in run.error.detail
    assert h.mappings.live == before
    assert h.mappings.staging == {}
    assert run.finished_at == T0


async def test_undecryptable_credentials() -> None:
    h = make(EncryptedCredentials("garbage", "garbage", T0, T0))
    run = await h.run_to_end()
    assert run.error is not None
    assert run.error.code is RunErrorCode.CREDENTIALS_UNDECRYPTABLE
    assert "update" in run.error.detail


async def test_not_enough_sessions_fails_as_alpaca_data_problem() -> None:
    h = make(registered())
    h.world.alpaca.sessions = h.world.alpaca.sessions[:5]
    run = await h.run_to_end()
    assert run.error is not None
    assert run.error.code is RunErrorCode.ALPACA_UNAVAILABLE


async def test_empty_universe_is_incomplete_data() -> None:
    h = make(registered())
    h.world.collector.catalog = []
    h.world.collector.markets = {}
    run = await h.run_to_end()
    assert run.error is not None
    assert run.error.code is RunErrorCode.COLLECTOR_INCOMPLETE_DATA


async def test_history_pruned_after_success_and_failure() -> None:
    h = make(registered())
    error = RunError(RunErrorCode.INTERNAL_ERROR, "x")
    for i in range(50):
        old = Run.start(f"old-{i:02d}", RunTrigger.MANUAL, T0 - timedelta(days=60 - i), {})
        await h.runs.insert_terminal(old.fail(old.started_at, error))
    ok = await h.run_to_end()
    assert await h.runs.count() == 50
    assert await h.runs.get("old-00") is None
    h.world.collector.fail_with = CollectorUnavailable()
    h.clock.advance(timedelta(minutes=1))
    failed = await h.run_to_end()
    assert await h.runs.count() == 50
    assert await h.runs.get("old-01") is None
    assert {ok.run_id, failed.run_id} <= set(h.runs.runs)


async def test_every_log_record_during_execution_carries_run_id() -> None:
    h = make(registered())
    seen: list[str | None] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.name.startswith("alpaca_gatherer.application.runs.execute_run"):
                seen.append(current_run_id.get())

    handler = Capture(level=logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(handler)
    old_level = root.level
    root.setLevel(logging.DEBUG)
    try:
        run = await h.run_to_end()
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)
    assert seen
    assert set(seen) == {run.run_id}
    assert current_run_id.get() is None


async def test_cancel_active_leaves_run_running() -> None:
    h = make(registered())
    h.world.collector.delay = 10
    run = await h.start()
    await asyncio.sleep(0)
    await h.start.cancel_active()
    stored = await h.runs.get(run.run_id)
    assert stored is not None
    assert stored.status is RunStatus.RUNNING
    assert h.start.active_task is None
    await h.start.cancel_active()  # no-op without an active task


async def test_get_and_list_runs() -> None:
    h = make(registered())
    first = await h.run_to_end()
    h.clock.advance(timedelta(hours=1))
    second = await h.run_to_end()
    assert await GetRun(h.runs)(first.run_id) == first
    with pytest.raises(RunNotFound):
        await GetRun(h.runs)("nope")
    page = await ListRuns(h.runs)(limit=1, offset=0)
    assert [r.run_id for r in page.items] == [second.run_id]
    assert (page.total, page.limit, page.offset) == (2, 1, 0)
    live = h.mappings.live or {}
    assert all(m.status is MatchStatus.MATCHED for m in live.values())
