"""``/api/v1/thresholds``: the thresholds the matching process uses."""

from fastapi import APIRouter

from alpaca_gatherer.interface.api.deps import ContainerDep
from alpaca_gatherer.interface.api.v1.schemas.thresholds import ThresholdsResponse

__all__ = ["router"]

router = APIRouter(prefix="/thresholds", tags=["thresholds"])


@router.get(
    "",
    operation_id="getThresholds",
    summary="Thresholds currently used by the matching process",
    response_model=ThresholdsResponse,
)
async def get_thresholds(container: ContainerDep) -> ThresholdsResponse:
    """Thresholds grouped by matching stage."""
    return ThresholdsResponse.of(container.get_thresholds())
