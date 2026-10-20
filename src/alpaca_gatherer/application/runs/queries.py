"""Read access to runs: one by id, or a page newest first (FR-012a)."""

from dataclasses import dataclass

from alpaca_gatherer.application.ports import RunRepository
from alpaca_gatherer.domain.errors import RunNotFound
from alpaca_gatherer.domain.runs import Run

__all__ = ["GetRun", "ListRuns", "RunPage"]


@dataclass(frozen=True, slots=True)
class RunPage:
    """A page of runs plus the total number retained."""

    items: list[Run]
    limit: int
    offset: int
    total: int


class GetRun:
    """Return one retained run; ``RunNotFound`` if unknown or pruned."""

    def __init__(self, runs: RunRepository) -> None:
        self._runs = runs

    async def __call__(self, run_id: str) -> Run:
        """Look up a run by id."""
        run = await self._runs.get(run_id)
        if run is None:
            raise RunNotFound(f"No retained run has id {run_id!r}.")
        return run


class ListRuns:
    """Return a page of runs, newest first."""

    def __init__(self, runs: RunRepository) -> None:
        self._runs = runs

    async def __call__(self, limit: int = 20, offset: int = 0) -> RunPage:
        """List runs."""
        items = await self._runs.list(limit, offset)
        return RunPage(items=items, limit=limit, offset=offset, total=await self._runs.count())
