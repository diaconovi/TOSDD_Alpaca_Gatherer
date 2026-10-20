"""``/api/v1/credentials`` end to end, including SC-003 (no plain value anywhere)."""

import logging

import pytest

from alpaca_gatherer.infrastructure.db.client import Collections, MongoDatabase
from tests.conftest import AppFactory

KEY = "PKPLAINKEY0123456789"
SECRET = "plainSecretValue/abcdefghijklmnop"
BODY = {"api_key": KEY, "api_secret": SECRET}


async def test_register_then_conflict_then_update(
    app_factory: AppFactory,
    db: MongoDatabase,
    collections: Collections,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    async with app_factory() as (_, client):
        created = await client.post("/api/v1/credentials", json=BODY)
        again = await client.post("/api/v1/credentials", json=BODY)
        updated = await client.patch(
            "/api/v1/credentials", json={"api_key": KEY + "2", "api_secret": SECRET + "2"}
        )
    assert created.status_code == 201
    assert created.content == b""
    assert again.status_code == 409
    assert again.json()["type"] == "urn:alpaca-gatherer:problem:credentials_exist"
    assert updated.status_code == 204
    assert updated.content == b""

    doc = await db[collections.credentials].find_one({})
    assert doc is not None
    for plain in (KEY, SECRET, KEY + "2", SECRET + "2"):
        assert plain not in str(doc)
        assert plain not in caplog.text
        assert plain not in again.text


async def test_patch_before_post_is_not_found(app_factory: AppFactory) -> None:
    async with app_factory() as (_, client):
        response = await client.patch("/api/v1/credentials", json=BODY)
    assert response.status_code == 404
    assert response.json()["type"] == "urn:alpaca-gatherer:problem:credentials_not_found"


@pytest.mark.parametrize(
    "body",
    [
        {"api_key": KEY},
        {"api_secret": SECRET},
        {"api_key": "", "api_secret": SECRET},
        {"api_key": KEY, "api_secret": ""},
        {**BODY, "extra": "x"},
        {},
    ],
)
@pytest.mark.parametrize("method", ["POST", "PATCH"])
async def test_invalid_bodies_are_422_without_echo(
    app_factory: AppFactory, body: dict[str, str], method: str
) -> None:
    async with app_factory() as (_, client):
        response = await client.request(method, "/api/v1/credentials", json=body)
    assert response.status_code == 422
    assert response.json()["type"] == "urn:alpaca-gatherer:problem:validation_error"
    assert KEY not in response.text
    assert SECRET not in response.text
