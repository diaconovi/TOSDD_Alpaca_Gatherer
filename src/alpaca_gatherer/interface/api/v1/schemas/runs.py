"""Response models of ``/api/v1/runs`` (``RunAccepted``, ``Run``, ``RunPage``)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from alpaca_gatherer.application.runs.queries import RunPage
from alpaca_gatherer.domain.runs import Run

__all__ = [
    "RunAcceptedResponse",
    "RunCountsResponse",
    "RunErrorResponse",
    "RunPageResponse",
    "RunResponse",
]


class RunAcceptedResponse(BaseModel):
    """Acknowledgement of a started run."""

    run_id: str
    status: Literal["running"] = "running"
    started_at: datetime


class RunCountsResponse(BaseModel):
    """Mapping records by status, and non-matched records by reason code."""

    matched: int
    ambiguous: int
    unmatched: int
    total: int
    by_reason: dict[str, int]


class RunErrorResponse(BaseModel):
    """Failure cause of a run."""

    code: str
    detail: str


class RunResponse(BaseModel):
    """One run."""

    run_id: str
    trigger: Literal["manual", "scheduled"]
    status: Literal["running", "succeeded", "failed"]
    started_at: datetime
    finished_at: datetime | None
    price_window_end: datetime
    counts: RunCountsResponse | None
    error: RunErrorResponse | None

    @classmethod
    def of(cls, run: Run) -> RunResponse:
        """Build from a domain run."""
        counts = run.counts
        return cls(
            run_id=run.run_id,
            trigger=run.trigger.value,
            status=run.status.value,
            started_at=run.started_at,
            finished_at=run.finished_at,
            price_window_end=run.price_window_end,
            counts=RunCountsResponse(
                matched=counts.matched,
                ambiguous=counts.ambiguous,
                unmatched=counts.unmatched,
                total=counts.total,
                by_reason=dict(counts.by_reason),
            )
            if counts
            else None,
            error=RunErrorResponse(code=run.error.code.value, detail=run.error.detail)
            if run.error
            else None,
        )


class RunPageResponse(BaseModel):
    """A page of runs, newest first."""

    items: list[RunResponse]
    limit: int
    offset: int
    total: int

    @classmethod
    def of(cls, page: RunPage) -> RunPageResponse:
        """Build from a page of domain runs."""
        return cls(
            items=[RunResponse.of(r) for r in page.items],
            limit=page.limit,
            offset=page.offset,
            total=page.total,
        )
