"""FastAPI dependencies: typed access to the services wired in ``main.py``.

Routes depend on these accessors only. A future authentication dependency (FR-027) attaches here.
"""

from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, Request

from alpaca_gatherer.application.credentials import RegisterCredentials, UpdateCredentials
from alpaca_gatherer.application.mappings import LookupMapping
from alpaca_gatherer.application.runs.queries import GetRun, ListRuns
from alpaca_gatherer.application.runs.start_run import StartRun
from alpaca_gatherer.application.schedule import GetSchedule, SetSchedule
from alpaca_gatherer.application.thresholds import GetThresholds

__all__ = ["Container", "ContainerDep", "get_container"]


@dataclass(frozen=True, slots=True)
class Container:
    """Every use case the HTTP interface calls, wired at startup."""

    get_thresholds: GetThresholds
    lookup_mapping: LookupMapping
    register_credentials: RegisterCredentials
    update_credentials: UpdateCredentials
    start_run: StartRun
    get_run: GetRun
    list_runs: ListRuns
    get_schedule: GetSchedule
    set_schedule: SetSchedule


def get_container(request: Request) -> Container:
    """Return the container stored on the application state by the lifespan."""
    return cast(Container, request.app.state.container)


ContainerDep = Annotated[Container, Depends(get_container)]
