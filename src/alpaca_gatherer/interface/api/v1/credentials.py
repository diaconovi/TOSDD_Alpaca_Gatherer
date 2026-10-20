"""``/api/v1/credentials``: register and replace the Alpaca credentials (write-only)."""

from fastapi import APIRouter, Response, status

from alpaca_gatherer.interface.api.deps import ContainerDep
from alpaca_gatherer.interface.api.problems import Problem
from alpaca_gatherer.interface.api.v1.schemas.credentials import CredentialsRequest

__all__ = ["router"]

router = APIRouter(prefix="/credentials", tags=["credentials"])


@router.post(
    "",
    operation_id="registerCredentials",
    summary="Register Alpaca credentials",
    status_code=status.HTTP_201_CREATED,
    response_class=Response,
    responses={
        201: {"description": "Registered. Empty body."},
        409: {"model": Problem},
        422: {"model": Problem},
    },
)
async def register_credentials(body: CredentialsRequest, container: ContainerDep) -> Response:
    """Store the key and secret encrypted; 409 if credentials are already registered."""
    await container.register_credentials(
        body.api_key.get_secret_value(), body.api_secret.get_secret_value()
    )
    return Response(status_code=status.HTTP_201_CREATED)


@router.patch(
    "",
    operation_id="updateCredentials",
    summary="Replace the stored Alpaca credentials",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={
        204: {"description": "Updated."},
        404: {"model": Problem},
        422: {"model": Problem},
    },
)
async def update_credentials(body: CredentialsRequest, container: ContainerDep) -> Response:
    """Replace the stored key and secret; 404 if none are registered."""
    await container.update_credentials(
        body.api_key.get_secret_value(), body.api_secret.get_secret_value()
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
