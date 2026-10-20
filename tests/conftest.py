"""Shared test harness.

* Tests under ``tests/integration`` are marked ``integration`` and need a real MongoDB given by
  ``MONGO_TEST_URL`` (e.g. ``mongodb://localhost:27017``). Without it the session fails, unless
  pytest runs with ``--allow-no-mongo``, which skips only those tests.
* Each test session uses a uniquely named database that is dropped at the end; each test gets its
  own collection names.
"""

import os
import uuid
import warnings
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest
import yaml
from cryptography.fernet import Fernet
from fastapi import FastAPI
from pymongo import MongoClient as SyncMongoClient
from pymongo.errors import PyMongoError

from alpaca_gatherer.config import Settings
from alpaca_gatherer.infrastructure.db.client import (
    Collections,
    MongoClient,
    MongoDatabase,
    create_mongo_client,
)
from alpaca_gatherer.main import Overrides, create_app
from tests.fakes import FrozenClock

MONGO_ENV = "MONGO_TEST_URL"
KIND_BY_DIRECTORY = {"integration": "integration", "contract": "contract", "golden": "golden"}

TEST_THRESHOLDS: dict[str, dict[str, Any]] = {
    "candidates": {"name_ratio": 0.88, "max_name_candidates": 2},
    "window": {"sessions": 5, "embargo_minutes": 15, "min_bars": 12, "feed": "iex"},
    "price": {"price_tol_pct": 1.25, "spread_mult": 0.4},
    "behavior": {
        "corr_threshold": 0.65,
        "dir_threshold": 0.7,
        "min_sig_moves": 4,
        "min_session_returns": 3,
    },
}

type AppFactory = Callable[..., AbstractAsyncContextManager[tuple[FastAPI, httpx.AsyncClient]]]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--allow-no-mongo",
        action="store_true",
        default=False,
        help=f"skip integration tests when {MONGO_ENV} is unset or unreachable",
    )


def _mongo_problem() -> str | None:
    url = os.environ.get(MONGO_ENV)
    if not url:
        return f"{MONGO_ENV} is not set"
    try:
        client: SyncMongoClient[dict[str, Any]]
        with SyncMongoClient(url, serverSelectionTimeoutMS=2000) as client:
            client.admin.command("ping")
    except PyMongoError as exc:
        return f"{MONGO_ENV}={url} is unreachable ({type(exc).__name__})"
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        for part in item.path.parts:
            if part in KIND_BY_DIRECTORY:
                item.add_marker(getattr(pytest.mark, KIND_BY_DIRECTORY[part]))
    integration = [i for i in items if i.get_closest_marker("integration")]
    if not integration:
        return
    problem = _mongo_problem()
    if problem is None:
        return
    if config.getoption("--allow-no-mongo"):
        warnings.warn(f"skipping {len(integration)} integration tests: {problem}", stacklevel=1)
        skip = pytest.mark.skip(reason=f"--allow-no-mongo: {problem}")
        for item in integration:
            item.add_marker(skip)
        return
    raise pytest.UsageError(
        f"Integration tests need MongoDB: {problem}. Set {MONGO_ENV} (e.g. "
        "mongodb://localhost:27017) or pass --allow-no-mongo to skip them."
    )


@pytest.fixture(scope="session")
def mongo_test_url() -> str:
    url = os.environ.get(MONGO_ENV)
    if not url:
        pytest.skip(f"{MONGO_ENV} is not set")
    return url


@pytest.fixture(scope="session")
def test_db_name() -> str:
    return f"alpaca_gatherer_test_{uuid.uuid4().hex[:12]}"


@pytest.fixture(scope="session")
async def mongo_client(mongo_test_url: str, test_db_name: str) -> AsyncIterator[MongoClient]:
    client = create_mongo_client(mongo_test_url, server_selection_timeout_ms=3000)
    yield client
    await client.drop_database(test_db_name)
    await client.close()


@pytest.fixture
def db(mongo_client: MongoClient, test_db_name: str) -> MongoDatabase:
    return mongo_client[test_db_name]


@pytest.fixture
def collections() -> Collections:
    return Collections(f"m{uuid.uuid4().hex[:10]}")


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock()


@pytest.fixture
def thresholds_file(tmp_path: Path) -> Path:
    path = tmp_path / "thresholds.yaml"
    path.write_text(yaml.safe_dump(TEST_THRESHOLDS))
    return path


@pytest.fixture
def make_settings(
    mongo_test_url: str, test_db_name: str, collections: Collections, thresholds_file: Path
) -> Callable[..., Settings]:
    parts = urlsplit(mongo_test_url)
    mongo_url = urlunsplit((parts.scheme, parts.hostname or "localhost", "", "", ""))

    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "collector_url": "http://collector.test:8001",
            "mongo_url": mongo_url,
            "mongo_port": parts.port or 27017,
            "mongo_mapping_db": test_db_name,
            "mongo_mapping_collection": collections.mapping,
            "field_encryption_key": Fernet.generate_key().decode(),
            "thresholds_file": thresholds_file,
            "logging": "DEBUG",
        }
        values.update(overrides)
        return Settings.model_validate(values)

    return factory


@pytest.fixture
def app_factory(make_settings: Callable[..., Settings], clock: FrozenClock) -> AppFactory:
    """Build the real app (with lifespan) against the test database; adapters can be faked."""

    @asynccontextmanager
    async def factory(
        overrides: Overrides | None = None, settings: Settings | None = None
    ) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
        app = create_app(settings or make_settings(), overrides or Overrides(clock=clock))
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                yield app, client

    return factory
