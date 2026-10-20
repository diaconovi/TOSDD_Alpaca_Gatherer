"""``GET /api/v1/mappings`` end to end against a real MongoDB."""

import pytest

from alpaca_gatherer.infrastructure.db.client import Collections, MongoDatabase
from alpaca_gatherer.infrastructure.db.mapping_repo import to_document
from tests.conftest import AppFactory
from tests.samples import ambiguous, matched, unmatched

MAPPING_FIELDS = {
    "capital_epic",
    "status",
    "match_type",
    "alpaca_symbol",
    "candidates",
    "price_diff_pct",
    "direction_agreement",
    "return_correlation",
    "reason",
    "run_id",
    "updated_at",
}
CANDIDATE_FIELDS = {
    "alpaca_symbol",
    "kind",
    "tradable",
    "price_diff_pct",
    "direction_agreement",
    "return_correlation",
    "passed",
}


async def seed(db: MongoDatabase, collections: Collections) -> None:
    docs = [to_document(r) for r in (matched(), unmatched(), ambiguous())]
    await db[collections.mapping].insert_many(docs)


async def test_matched_by_epic_and_by_symbol_point_at_each_other(
    app_factory: AppFactory, db: MongoDatabase, collections: Collections
) -> None:
    async with app_factory() as (_, client):
        await seed(db, collections)
        by_epic = await client.get("/api/v1/mappings", params={"capital_epic": "BRKB"})
        by_symbol = await client.get("/api/v1/mappings", params={"alpaca_symbol": "BRK.B"})
    assert by_epic.status_code == by_symbol.status_code == 200
    body = by_epic.json()
    assert set(body) == MAPPING_FIELDS
    assert set(body["candidates"][0]) == CANDIDATE_FIELDS
    assert body["alpaca_symbol"] == "BRK.B"
    assert body["status"] == "matched"
    assert body["match_type"] == "alias"
    assert body["reason"] is None
    assert body["updated_at"] == "2026-10-08T06:30:00Z"
    assert by_symbol.json()["capital_epic"] == "BRKB"


async def test_unmatched_and_ambiguous_epics(
    app_factory: AppFactory, db: MongoDatabase, collections: Collections
) -> None:
    async with app_factory() as (_, client):
        await seed(db, collections)
        unmatched_body = (
            await client.get("/api/v1/mappings", params={"capital_epic": "APPL"})
        ).json()
        ambiguous_body = (
            await client.get("/api/v1/mappings", params={"capital_epic": "WSOB"})
        ).json()
    assert unmatched_body["status"] == "unmatched"
    assert unmatched_body["reason"]["code"] == "not_listed_on_alpaca"
    assert unmatched_body["reason"]["detail"]
    assert ambiguous_body["status"] == "ambiguous"
    assert ambiguous_body["alpaca_symbol"] is None
    assert [c["alpaca_symbol"] for c in ambiguous_body["candidates"]] == ["WSO", "WSO.B"]


@pytest.mark.parametrize(
    "params",
    [
        {"capital_epic": "BRKB", "alpaca_symbol": "BRK.B"},
        {},
        {"capital_epic": ""},
        {"alpaca_symbol": ""},
    ],
)
async def test_validation_errors(app_factory: AppFactory, params: dict[str, str]) -> None:
    async with app_factory() as (_, client):
        response = await client.get("/api/v1/mappings", params=params)
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "urn:alpaca-gatherer:problem:validation_error"
    assert body["errors"]


async def test_unknown_identifier_is_instrument_not_found(
    app_factory: AppFactory, db: MongoDatabase, collections: Collections
) -> None:
    async with app_factory() as (_, client):
        await seed(db, collections)
        by_epic = await client.get("/api/v1/mappings", params={"capital_epic": "ZZZZ"})
        by_ambiguous_symbol = await client.get("/api/v1/mappings", params={"alpaca_symbol": "WSO"})
    for response in (by_epic, by_ambiguous_symbol):
        assert response.status_code == 404
        assert response.json()["type"] == "urn:alpaca-gatherer:problem:instrument_not_found"


async def test_before_any_snapshot_is_mapping_not_available(app_factory: AppFactory) -> None:
    async with app_factory() as (_, client):
        response = await client.get("/api/v1/mappings", params={"capital_epic": "BRKB"})
    assert response.status_code == 404
    assert response.json()["type"] == "urn:alpaca-gatherer:problem:mapping_not_available"
