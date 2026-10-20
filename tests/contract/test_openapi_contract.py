"""The generated OpenAPI document stays in sync with ``contracts/openapi.yaml`` (Principle IV)."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from cryptography.fernet import Fernet

from alpaca_gatherer.config import Settings
from alpaca_gatherer.main import create_app

CONTRACT = Path(__file__).parents[2] / "specs/001-epic-symbol-mapping/contracts/openapi.yaml"
PREFIX = "/api/v1"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
# Contract schema name -> generated model name.
SCHEMAS = {
    "Problem": "Problem",
    "Thresholds": "ThresholdsResponse",
    "RunAccepted": "RunAcceptedResponse",
    "Run": "RunResponse",
    "RunPage": "RunPageResponse",
    "ScheduleRequest": "ScheduleRequest",
    "ScheduleView": "ScheduleViewResponse",
    "Candidate": "CandidateResponse",
    "Mapping": "MappingResponse",
    "CredentialsRequest": "CredentialsRequest",
}


@pytest.fixture(scope="module")
def contract() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(CONTRACT.read_text())
    return data


@pytest.fixture(scope="module")
def generated() -> dict[str, Any]:
    settings = Settings.model_validate(
        {
            "collector_url": "http://collector.test:8001",
            "mongo_url": "mongodb://localhost",
            "mongo_mapping_db": "unused",
            "mongo_mapping_collection": "unused",
            "field_encryption_key": Fernet.generate_key().decode(),
        }
    )
    return create_app(settings).openapi()


def _operations(spec: dict[str, Any], prefix: str = "") -> dict[tuple[str, str], set[str]]:
    return {
        (prefix + path, method): set(op.get("responses", {}))
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if method in HTTP_METHODS
    }


def test_paths_and_methods_match(contract: dict[str, Any], generated: dict[str, Any]) -> None:
    assert set(_operations(contract, PREFIX)) == set(_operations(generated))


def test_operation_ids_match(contract: dict[str, Any], generated: dict[str, Any]) -> None:
    def ids(spec: dict[str, Any], prefix: str = "") -> dict[tuple[str, str], str]:
        return {
            (prefix + path, method): op["operationId"]
            for path, item in spec["paths"].items()
            for method, op in item.items()
            if method in HTTP_METHODS
        }

    assert ids(contract, PREFIX) == ids(generated)


def test_status_codes_match(contract: dict[str, Any], generated: dict[str, Any]) -> None:
    expected = _operations(contract, PREFIX)
    actual = _operations(generated)
    for key, codes in expected.items():
        # FastAPI documents 422 on every operation with parameters; the contract only where useful.
        assert actual[key] - {"422"} == codes - {"422"}, key
        assert codes <= actual[key], key


@pytest.mark.parametrize(("contract_name", "model_name"), sorted(SCHEMAS.items()))
def test_schema_field_names_match(
    contract: dict[str, Any], generated: dict[str, Any], contract_name: str, model_name: str
) -> None:
    expected = contract["components"]["schemas"][contract_name].get("properties", {})
    actual = generated["components"]["schemas"][model_name].get("properties", {})
    assert set(actual) == set(expected)
