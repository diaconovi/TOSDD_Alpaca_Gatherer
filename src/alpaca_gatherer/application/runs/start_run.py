"""Start a matching run in the background (FR-008, FR-009).

The authoritative single-run lock is the database index (``insert_running`` raises
``RunInProgress``); the in-process ``asyncio.Lock`` only serializes local start attempts. A manual
request that collides gets ``RunInProgress``; a scheduled trigger that collides, or that fires
before credentials exist, is recorded as a failed run instead (research R6).
"""

import asyncio
import logging
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

from alpaca_gatherer.application.credentials import CredentialsProvider
from alpaca_gatherer.application.ports import Clock, RunRepository
from alpaca_gatherer.domain.errors import CredentialsMissing, RunInProgress
from alpaca_gatherer.domain.runs import Run, RunError, RunErrorCode, RunTrigger
from alpaca_gatherer.domain.thresholds import Thresholds

__all__ = ["RunExecutor", "StartRun"]

log = logging.getLogger(__name__)

type RunExecutor = Callable[[Run], Coroutine[Any, Any, Run]]


class StartRun:
    """Create a ``running`` run and launch its execution as a background task."""

    def __init__(
        self,
        *,
        credentials: CredentialsProvider,
        runs: RunRepository,
        execute: RunExecutor,
        clock: Clock,
        thresholds: Thresholds,
        history_limit: int,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._credentials = credentials
        self._runs = runs
        self._execute = execute
        self._clock = clock
        self._thresholds = thresholds
        self._history_limit = history_limit
        self._new_id = id_factory
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[Run] | None = None

    @property
    def active_task(self) -> asyncio.Task[Run] | None:
        """The background task of the run started by this process, while it is running."""
        return self._task if self._task is not None and not self._task.done() else None

    async def __call__(self, trigger: RunTrigger = RunTrigger.MANUAL) -> Run:
        """Start a run. Manual: raises ``CredentialsMissing`` or ``RunInProgress``.
        Scheduled: such outcomes are recorded as failed runs and returned."""
        if not await self._credentials.exists():
            if trigger is RunTrigger.SCHEDULED:
                return await self._record_failure(
                    RunErrorCode.CREDENTIALS_MISSING,
                    "scheduled run not started: no Alpaca credentials are registered",
                )
            raise CredentialsMissing()
        async with self._lock:
            run = Run.start(self._new_id(), trigger, self._clock.now(), self._thresholds.as_dict())
            try:
                await self._runs.insert_running(run)
            except RunInProgress as exc:
                if trigger is RunTrigger.SCHEDULED:
                    return await self._record_failure(
                        RunErrorCode.SKIPPED_CONCURRENT_RUN,
                        f"scheduled run skipped: run {exc.active_run_id} was still running",
                    )
                raise
            self._task = asyncio.create_task(self._execute(run), name=f"run-{run.run_id}")
        log.info("run %s accepted (trigger=%s)", run.run_id, trigger)
        return run

    async def _record_failure(self, code: RunErrorCode, detail: str) -> Run:
        run = Run.skipped(
            self._new_id(), self._clock.now(), self._thresholds.as_dict(), RunError(code, detail)
        )
        await self._runs.insert_terminal(run)
        log.warning("%s (recorded as run %s)", detail, run.run_id)
        await self._runs.prune(self._history_limit)
        return run

    async def cancel_active(self) -> None:
        """Cancel the background run (at shutdown); the next startup records it as interrupted."""
        task = self.active_task
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # the run records its own failures; nothing more to do here
            log.exception("run task ended with an error during shutdown")
