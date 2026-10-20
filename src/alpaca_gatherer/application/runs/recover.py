"""Startup recovery (FR-012b): fail interrupted runs and drop leftover staging collections.

The live mapping is never touched and no run is started.
"""

import logging

from alpaca_gatherer.application.ports import Clock, MappingRepository, RunRepository

__all__ = ["RecoverOnStartup"]

log = logging.getLogger(__name__)


class RecoverOnStartup:
    """Mark ``running`` runs as ``failed/interrupted_by_restart`` and clean staging."""

    def __init__(self, runs: RunRepository, mappings: MappingRepository, clock: Clock) -> None:
        self._runs = runs
        self._mappings = mappings
        self._clock = clock

    async def __call__(self) -> list[str]:
        """Recover; return the ids of the runs marked as interrupted."""
        interrupted = await self._runs.mark_running_as_interrupted(self._clock.now())
        for run_id in interrupted:
            log.warning("run %s was interrupted by a service restart; marked failed", run_id)
        dropped = await self._mappings.drop_all_staging()
        if dropped:
            log.info("dropped leftover staging collections: %s", ", ".join(dropped))
        return interrupted
