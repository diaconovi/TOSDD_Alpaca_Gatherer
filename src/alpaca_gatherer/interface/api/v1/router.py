"""The ``/api/v1`` router: mounts one sub-router per resource."""

from fastapi import APIRouter

from alpaca_gatherer.interface.api.v1 import credentials, mappings, runs, schedules, thresholds

__all__ = ["build_v1_router"]


def build_v1_router() -> APIRouter:
    """Return the v1 router with every resource mounted."""
    router = APIRouter(prefix="/api/v1")
    router.include_router(thresholds.router)
    router.include_router(runs.router)
    router.include_router(schedules.router)
    router.include_router(mappings.router)
    router.include_router(credentials.router)
    return router
