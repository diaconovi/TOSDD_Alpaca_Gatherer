"""Execute one matching run end to end and record its outcome.

Stages: decrypt credentials → Alpaca assets and calendar → window ending at the run start →
Capital.com universe (catalogs + sweep) → candidates → bars → checks → classification → staging
write → atomic swap. Any failure drops the staging collection, leaves the live mapping untouched and
records the run as ``failed`` with an error code. History is pruned after every terminal state.
"""

import asyncio
import logging
from dataclasses import replace

from alpaca_gatherer.application.credentials import CredentialsProvider
from alpaca_gatherer.application.ports import (
    AlpacaMarketPort,
    CapitalCatalogPort,
    Clock,
    MappingRepository,
    RunRepository,
)
from alpaca_gatherer.application.runs.market_data import gather_market_data
from alpaca_gatherer.domain.errors import CredentialsMissing, DomainError
from alpaca_gatherer.domain.mapping import InstrumentMapping
from alpaca_gatherer.domain.matching.pipeline import match_universe
from alpaca_gatherer.domain.runs import Run, RunCounts, RunError, RunErrorCode, RunWindow
from alpaca_gatherer.domain.thresholds import Thresholds
from alpaca_gatherer.logging_setup import current_run_id

__all__ = ["ExecuteRun", "error_code_of"]

log = logging.getLogger(__name__)

INTERNAL_DETAIL = "unexpected error during the run; see the service log"


def error_code_of(exc: DomainError) -> RunErrorCode:
    """Map a domain error onto a run error code (``internal_error`` if it has none)."""
    try:
        return RunErrorCode(exc.code)
    except ValueError:
        return RunErrorCode.INTERNAL_ERROR


class ExecuteRun:
    """Runs the matching process for a ``running`` run and stores the result."""

    def __init__(
        self,
        *,
        credentials: CredentialsProvider,
        collector: CapitalCatalogPort,
        alpaca: AlpacaMarketPort,
        mappings: MappingRepository,
        runs: RunRepository,
        clock: Clock,
        thresholds: Thresholds,
        history_limit: int,
    ) -> None:
        self._credentials = credentials
        self._collector = collector
        self._alpaca = alpaca
        self._mappings = mappings
        self._runs = runs
        self._clock = clock
        self._thresholds = thresholds
        self._history_limit = history_limit

    async def __call__(self, run: Run) -> Run:
        """Execute ``run``; return its terminal state (cancellation propagates unrecorded)."""
        token = current_run_id.set(run.run_id)
        window: RunWindow | None = None
        try:
            log.info("run started (trigger=%s)", run.trigger)
            records, window = await self._match(run)
            finished_at = self._clock.now()
            records = [replace(r, updated_at=finished_at) for r in records]
            await self._mappings.write_staging(run.run_id, records)
            await self._mappings.swap(run.run_id)
            done = run.succeed(finished_at, RunCounts.of(records), window)
            await self._runs.finish(done)
            log.info("run succeeded: %s", done.counts)
        except asyncio.CancelledError:
            log.warning("run cancelled; it will be recorded as interrupted at the next start")
            raise
        except DomainError as exc:
            done = await self._fail(run, RunError(error_code_of(exc), exc.detail), window)
        except Exception:
            log.exception("run failed unexpectedly")
            done = await self._fail(
                run, RunError(RunErrorCode.INTERNAL_ERROR, INTERNAL_DETAIL), window
            )
        else:
            await self._prune()
        finally:
            current_run_id.reset(token)
        return done

    async def _fail(self, run: Run, error: RunError, window: RunWindow | None) -> Run:
        log.warning("run failed: %s: %s", error.code, error.detail)
        try:
            await self._mappings.drop_staging(run.run_id)
        except Exception:
            log.exception("could not drop the staging collection")
        failed = run.fail(self._clock.now(), error, window)
        await self._runs.finish(failed)
        await self._prune()
        return failed

    async def _prune(self) -> None:
        try:
            deleted = await self._runs.prune(self._history_limit)
        except Exception:
            log.exception("run history pruning failed")
            return
        if deleted:
            log.info("pruned %d old runs", deleted)

    async def _match(self, run: Run) -> tuple[list[InstrumentMapping], RunWindow]:
        creds = await self._credentials.load_plain()
        if creds is None:
            raise CredentialsMissing()
        data = await gather_market_data(
            credentials=creds,
            collector=self._collector,
            alpaca=self._alpaca,
            thresholds=self._thresholds,
            window_end=run.price_window_end,
        )
        records = await asyncio.to_thread(
            match_universe,
            data.plan,
            data.histories,
            data.bars,
            data.sessions,
            run_id=run.run_id,
            produced_at=run.started_at,
        )
        return records, data.window
