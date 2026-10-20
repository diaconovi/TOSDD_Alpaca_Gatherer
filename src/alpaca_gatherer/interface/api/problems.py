"""RFC 7807 problem details: the single place where errors become HTTP responses.

>>> problem_type("run_in_progress")
'urn:alpaca-gatherer:problem:run_in_progress'
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from alpaca_gatherer.domain.errors import DomainError, InvalidRequest, RunInProgress

__all__ = [
    "PROBLEM_MEDIA_TYPE",
    "STATUS_BY_CODE",
    "Problem",
    "ProblemFieldError",
    "problem_type",
    "register_problem_handlers",
]

log = logging.getLogger(__name__)

PROBLEM_MEDIA_TYPE = "application/problem+json"

STATUS_BY_CODE: dict[str, int] = {
    "validation_error": 422,
    "run_in_progress": 409,
    "credentials_missing": 409,
    "credentials_exist": 409,
    "credentials_not_found": 404,
    "run_not_found": 404,
    "instrument_not_found": 404,
    "mapping_not_available": 404,
    "credentials_undecryptable": 500,
    "collector_unavailable": 502,
    "collector_incomplete_data": 502,
    "alpaca_unavailable": 502,
    "alpaca_auth_failed": 502,
    "internal_error": 500,
}
"""HTTP status of every problem code (contracts/problems.md)."""


class ProblemFieldError(BaseModel):
    """One offending field of a ``validation_error``."""

    loc: list[str]
    msg: str


class Problem(BaseModel):
    """RFC 7807 problem details document."""

    type: str
    title: str
    status: int
    detail: str
    instance: str | None = None
    active_run_id: str | None = None
    errors: list[ProblemFieldError] | None = None


def problem_type(code: str) -> str:
    """Return the ``type`` URI of a problem code."""
    return f"urn:alpaca-gatherer:problem:{code}"


def _response(problem: Problem) -> JSONResponse:
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=problem.status,
        media_type=PROBLEM_MEDIA_TYPE,
    )


_QUERY_FIELDS = frozenset({"capital_epic", "alpaca_symbol", "limit", "offset"})


def _field_loc(field: str) -> list[str]:
    parts = field.split(".")
    return ["query" if parts[0] in _QUERY_FIELDS else "body", *parts]


async def _domain_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    status = STATUS_BY_CODE.get(exc.code, 500)
    problem = Problem(
        type=problem_type(exc.code),
        title=exc.title,
        status=status,
        detail=exc.detail,
        instance=request.url.path,
    )
    if isinstance(exc, RunInProgress):
        problem.active_run_id = exc.active_run_id
    if isinstance(exc, InvalidRequest):
        problem.errors = [ProblemFieldError(loc=_field_loc(exc.field), msg=exc.message)]
    return _response(problem)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    raw: list[dict[str, Any]] = list(exc.errors())
    errors = [
        ProblemFieldError(loc=[str(part) for part in err.get("loc", ())], msg=str(err.get("msg")))
        for err in raw
    ]
    fields = ", ".join(".".join(e.loc[1:]) or e.loc[0] for e in errors if e.loc)
    return _response(
        Problem(
            type=problem_type("validation_error"),
            title="Validation error",
            status=422,
            detail=f"The request is invalid ({fields})." if fields else "The request is invalid.",
            instance=request.url.path,
            errors=errors,
        )
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    title = {404: "Not found", 405: "Method not allowed"}.get(exc.status_code, "HTTP error")
    return _response(
        Problem(
            type=problem_type(f"http_{exc.status_code}"),
            title=title,
            status=exc.status_code,
            detail=str(exc.detail) if exc.detail else title,
            instance=request.url.path,
        )
    )


async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return _response(
        Problem(
            type=problem_type("internal_error"),
            title="Internal error",
            status=500,
            detail="An unexpected error occurred.",
            instance=request.url.path,
        )
    )


def register_problem_handlers(app: FastAPI) -> None:
    """Make every error raised while serving ``app`` an ``application/problem+json`` response."""
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unexpected)
