"""``/api/v1/schedules/current``: the single matching schedule."""

from fastapi import APIRouter

from alpaca_gatherer.interface.api.deps import ContainerDep
from alpaca_gatherer.interface.api.problems import Problem
from alpaca_gatherer.interface.api.v1.schemas.schedules import (
    ScheduleRequest,
    ScheduleViewResponse,
)

__all__ = ["router"]

router = APIRouter(prefix="/schedules", tags=["schedules"])


@router.get(
    "/current",
    operation_id="getSchedule",
    summary="Current schedule, next run, last completed run and timezone",
    response_model=ScheduleViewResponse,
)
async def get_schedule(container: ContainerDep) -> ScheduleViewResponse:
    """Times are rendered in the schedule's timezone; with no schedule, in UTC."""
    return ScheduleViewResponse.of(await container.get_schedule())


@router.put(
    "/current",
    operation_id="putSchedule",
    summary="Replace the schedule, or remove it with schedule: null",
    response_model=ScheduleViewResponse,
    responses={422: {"model": Problem}},
)
async def put_schedule(body: ScheduleRequest, container: ContainerDep) -> ScheduleViewResponse:
    """Apply a cron, recurring or one-time schedule; invalid input changes nothing."""
    view = await container.set_schedule(body.model_dump(exclude_unset=True))
    return ScheduleViewResponse.of(view)
