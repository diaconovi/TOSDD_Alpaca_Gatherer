"""``/api/v1/runs``: start matching runs and inspect them."""

from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from alpaca_gatherer.domain.runs import RunTrigger
from alpaca_gatherer.interface.api.deps import ContainerDep
from alpaca_gatherer.interface.api.problems import Problem
from alpaca_gatherer.interface.api.v1.schemas.runs import (
    RunAcceptedResponse,
    RunPageResponse,
    RunResponse,
)

__all__ = ["router"]

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post(
    "",
    operation_id="startRun",
    summary="Start a full matching run in the background",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunAcceptedResponse,
    responses={409: {"model": Problem}},
)
async def start_run(container: ContainerDep, response: Response) -> RunAcceptedResponse:
    """Takes no body or options. The price-data window ends at the run's start time."""
    run = await container.start_run(RunTrigger.MANUAL)
    response.headers["Location"] = f"/api/v1/runs/{run.run_id}"
    return RunAcceptedResponse(run_id=run.run_id, started_at=run.started_at)


@router.get(
    "",
    operation_id="listRuns",
    summary="List recent runs, newest first",
    response_model=RunPageResponse,
    responses={422: {"model": Problem}},
)
async def list_runs(
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunPageResponse:
    """A page of retained runs."""
    return RunPageResponse.of(await container.list_runs(limit, offset))


@router.get(
    "/{run_id}",
    operation_id="getRun",
    summary="One run by identifier",
    response_model=RunResponse,
    responses={404: {"model": Problem}},
)
async def get_run(run_id: str, container: ContainerDep) -> RunResponse:
    """A retained run; 404 if unknown or pruned."""
    return RunResponse.of(await container.get_run(run_id))
