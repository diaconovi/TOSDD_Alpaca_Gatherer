"""RFC 7807 problem details (contracts/problems.md)."""

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from alpaca_gatherer.domain import errors
from alpaca_gatherer.interface.api.problems import PROBLEM_MEDIA_TYPE, register_problem_handlers

CASES: list[tuple[errors.DomainError, int, str]] = [
    (errors.RunInProgress("abc"), 409, "run_in_progress"),
    (errors.CredentialsMissing(), 409, "credentials_missing"),
    (errors.CredentialsExist(), 409, "credentials_exist"),
    (errors.CredentialsNotFound(), 404, "credentials_not_found"),
    (errors.RunNotFound(), 404, "run_not_found"),
    (errors.InstrumentNotFound(), 404, "instrument_not_found"),
    (errors.MappingNotAvailable(), 404, "mapping_not_available"),
    (errors.ScheduleValidationError("schedule.day", "bad"), 422, "validation_error"),
    (errors.InvalidRequest("capital_epic", "bad"), 422, "validation_error"),
    (errors.CredentialsUndecryptable(), 500, "credentials_undecryptable"),
    (errors.CollectorUnavailable(), 502, "collector_unavailable"),
    (errors.CollectorIncompleteData(), 502, "collector_incomplete_data"),
    (errors.AlpacaUnavailable(), 502, "alpaca_unavailable"),
    (errors.AlpacaAuthFailed(), 502, "alpaca_auth_failed"),
]


class Body(BaseModel):
    name: str


def make_app(exc: Exception | None = None) -> FastAPI:
    app = FastAPI()
    register_problem_handlers(app)

    @app.get("/raise")
    async def raise_it() -> None:
        assert exc is not None
        raise exc

    @app.post("/body")
    async def body(payload: Body) -> dict[str, str]:
        return {"name": payload.name}

    return app


async def call(app: FastAPI, method: str, path: str, json: object = None) -> httpx.Response:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, json=json)


@pytest.mark.parametrize(("exc", "status", "code"), CASES)
async def test_domain_errors_map_to_status_and_type(
    exc: errors.DomainError, status: int, code: str
) -> None:
    response = await call(make_app(exc), "GET", "/raise")
    assert response.status_code == status
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    assert body["type"] == f"urn:alpaca-gatherer:problem:{code}"
    assert body["status"] == status
    assert body["title"]
    assert body["detail"]
    assert body["instance"] == "/raise"


async def test_run_in_progress_carries_active_run_id() -> None:
    response = await call(make_app(errors.RunInProgress("run-7")), "GET", "/raise")
    assert response.json()["active_run_id"] == "run-7"


async def test_domain_validation_error_lists_field() -> None:
    exc = errors.ScheduleValidationError("schedule.day", "not a weekday")
    body = (await call(make_app(exc), "GET", "/raise")).json()
    assert body["errors"] == [{"loc": ["body", "schedule", "day"], "msg": "not a weekday"}]


async def test_request_validation_error_is_422_with_errors() -> None:
    response = await call(make_app(), "POST", "/body", json={"wrong": 1})
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    body = response.json()
    assert body["type"] == "urn:alpaca-gatherer:problem:validation_error"
    assert body["errors"][0]["loc"] == ["body", "name"]
    assert isinstance(body["errors"][0]["msg"], str)


async def test_unexpected_exception_is_500_without_text() -> None:
    response = await call(make_app(RuntimeError("secret internals")), "GET", "/raise")
    assert response.status_code == 500
    body = response.json()
    assert body["type"] == "urn:alpaca-gatherer:problem:internal_error"
    assert "secret internals" not in response.text


async def test_unknown_route_is_a_problem() -> None:
    response = await call(make_app(), "GET", "/nowhere")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith(PROBLEM_MEDIA_TYPE)
    assert response.json()["status"] == 404
