"""``/api/v1/mappings``: translate an instrument between brokers."""

from typing import Annotated

from fastapi import APIRouter, Query

from alpaca_gatherer.interface.api.deps import ContainerDep
from alpaca_gatherer.interface.api.problems import Problem
from alpaca_gatherer.interface.api.v1.schemas.mappings import MappingResponse

__all__ = ["router"]

router = APIRouter(prefix="/mappings", tags=["mappings"])


@router.get(
    "",
    operation_id="lookupMapping",
    summary="Look up a mapping by exactly one of capital_epic or alpaca_symbol",
    response_model=MappingResponse,
    responses={404: {"model": Problem}, 422: {"model": Problem}},
)
async def lookup_mapping(
    container: ContainerDep,
    capital_epic: Annotated[str | None, Query(min_length=1)] = None,
    alpaca_symbol: Annotated[str | None, Query(min_length=1)] = None,
) -> MappingResponse:
    """Return the stored record. By epic: any status. By symbol: matched records only."""
    record = await container.lookup_mapping(capital_epic=capital_epic, alpaca_symbol=alpaca_symbol)
    return MappingResponse.of(record)
