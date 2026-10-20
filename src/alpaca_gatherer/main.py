"""Composition root: the app factory, dependency wiring and lifespan.

Start the service with ``uv run uvicorn alpaca_gatherer.main:app --host 127.0.0.1 --port 8002``.
Settings and thresholds are validated before anything is served; a bad value stops the process
with a message naming the variable or file.

Startup order: settings → thresholds → Mongo and indexes → recovery of interrupted runs →
schedule restore → scheduler start. Shutdown: stop the scheduler, cancel the active run task,
close the clients.
"""

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI
from to_collector_client import CollectorClient

from alpaca_gatherer.application.credentials import (
    CredentialsProvider,
    RegisterCredentials,
    UpdateCredentials,
)
from alpaca_gatherer.application.mappings import LookupMapping
from alpaca_gatherer.application.ports import (
    AlpacaMarketPort,
    CapitalCatalogPort,
    Clock,
    JobScheduler,
)
from alpaca_gatherer.application.runs.execute_run import ExecuteRun
from alpaca_gatherer.application.runs.queries import GetRun, ListRuns
from alpaca_gatherer.application.runs.recover import RecoverOnStartup
from alpaca_gatherer.application.runs.start_run import StartRun
from alpaca_gatherer.application.schedule import (
    GetSchedule,
    OnScheduledFire,
    RestoreScheduleOnStartup,
    SetSchedule,
)
from alpaca_gatherer.application.thresholds import GetThresholds
from alpaca_gatherer.config import ConfigError, Settings, load_settings, load_thresholds
from alpaca_gatherer.domain.thresholds import Thresholds
from alpaca_gatherer.infrastructure.clients.alpaca import AlpacaGateway
from alpaca_gatherer.infrastructure.clients.collector import CollectorGateway
from alpaca_gatherer.infrastructure.clock import SystemClock
from alpaca_gatherer.infrastructure.db.client import (
    Collections,
    MongoDatabase,
    create_mongo_client,
)
from alpaca_gatherer.infrastructure.db.credential_repo import MongoCredentialRepository
from alpaca_gatherer.infrastructure.db.indexes import ensure_indexes
from alpaca_gatherer.infrastructure.db.mapping_repo import MongoMappingRepository
from alpaca_gatherer.infrastructure.db.run_repo import MongoRunRepository
from alpaca_gatherer.infrastructure.db.schedule_repo import MongoScheduleRepository
from alpaca_gatherer.infrastructure.scheduler.apscheduler_adapter import ApschedulerJobScheduler
from alpaca_gatherer.infrastructure.security.fernet_cipher import FernetCipher
from alpaca_gatherer.interface.api.deps import Container
from alpaca_gatherer.interface.api.problems import register_problem_handlers
from alpaca_gatherer.interface.api.v1.router import build_v1_router
from alpaca_gatherer.logging_setup import configure_logging

__all__ = ["Overrides", "create_app"]

log = logging.getLogger("alpaca_gatherer")


@dataclass(frozen=True, slots=True)
class Overrides:
    """Replacement adapters, used by tests to run the real app against fakes."""

    clock: Clock | None = None
    collector: CapitalCatalogPort | None = None
    alpaca: AlpacaMarketPort | None = None
    scheduler: JobScheduler | None = None


@dataclass(frozen=True, slots=True)
class _Services:
    """Everything the lifespan starts and stops, plus the container for the routes."""

    container: Container
    recover: RecoverOnStartup
    restore_schedule: RestoreScheduleOnStartup
    scheduler: JobScheduler
    collector: CapitalCatalogPort
    alpaca: AlpacaMarketPort


def create_app(settings: Settings | None = None, overrides: Overrides | None = None) -> FastAPI:
    """Build the FastAPI application. Raises ``ConfigError`` on invalid settings or thresholds."""
    settings = settings or load_settings()
    thresholds = load_thresholds(settings.thresholds_file)
    overrides = overrides or Overrides()
    configure_logging(settings.logging, settings.time_zone)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client = create_mongo_client(settings.mongo_uri)
        services: _Services | None = None
        try:
            db = client[settings.mongo_mapping_db]
            collections = Collections(settings.mongo_mapping_collection)
            await ensure_indexes(db, collections)
            services = _wire(settings, thresholds, overrides, db, collections)
            await services.recover()
            await services.restore_schedule()
            services.scheduler.start()
            app.state.container = services.container
            log.info("service started; thresholds loaded from %s", settings.thresholds_file)
            yield
        finally:
            if services is not None:
                services.scheduler.shutdown()
                await services.container.start_run.cancel_active()
                await services.collector.aclose()
                await services.alpaca.aclose()
            await client.close()
            log.info("service stopped")

    app = FastAPI(
        title="Alpaca Gatherer",
        version="1.0.0",
        description=(
            "Keeps the mapping between Capital.com epics and Alpaca symbols up to date. "
            "No authentication in this version: bind to an internal or loopback address."
        ),
        lifespan=lifespan,
    )
    register_problem_handlers(app)
    app.include_router(build_v1_router())
    return app


def _collector(settings: Settings) -> CollectorGateway:
    scheme, host, port = settings.collector_endpoint
    return CollectorGateway(CollectorClient(host, port, scheme=scheme))


def _wire(
    settings: Settings,
    thresholds: Thresholds,
    overrides: Overrides,
    db: MongoDatabase,
    collections: Collections,
) -> _Services:
    clock = overrides.clock or SystemClock()
    collector = overrides.collector or _collector(settings)
    alpaca = overrides.alpaca or AlpacaGateway(
        settings.alpaca_trading_url, settings.alpaca_data_url
    )
    cipher = FernetCipher(settings.field_encryption_key.get_secret_value())
    mappings = MongoMappingRepository(db, collections)
    credentials = MongoCredentialRepository(db, collections)
    runs = MongoRunRepository(db, collections)
    provider = CredentialsProvider(credentials, cipher)
    execute = ExecuteRun(
        credentials=provider,
        collector=collector,
        alpaca=alpaca,
        mappings=mappings,
        runs=runs,
        clock=clock,
        thresholds=thresholds,
        history_limit=settings.run_history_limit,
    )
    start_run = StartRun(
        credentials=provider,
        runs=runs,
        execute=execute,
        clock=clock,
        thresholds=thresholds,
        history_limit=settings.run_history_limit,
    )
    scheduler = overrides.scheduler or ApschedulerJobScheduler()
    schedules = MongoScheduleRepository(db, collections)
    on_fire = OnScheduledFire(start_run, schedules)
    get_schedule = GetSchedule(schedules, runs, scheduler, clock)
    container = Container(
        get_thresholds=GetThresholds(thresholds),
        lookup_mapping=LookupMapping(mappings),
        register_credentials=RegisterCredentials(credentials, cipher, clock),
        update_credentials=UpdateCredentials(credentials, cipher, clock),
        start_run=start_run,
        get_run=GetRun(runs),
        list_runs=ListRuns(runs),
        get_schedule=get_schedule,
        set_schedule=SetSchedule(schedules, scheduler, clock, on_fire, get_schedule),
    )
    return _Services(
        container=container,
        recover=RecoverOnStartup(runs, mappings, clock),
        restore_schedule=RestoreScheduleOnStartup(schedules, scheduler, clock, on_fire),
        scheduler=scheduler,
        collector=collector,
        alpaca=alpaca,
    )


_apps: dict[str, FastAPI] = {}


def __getattr__(name: str) -> FastAPI:
    """Build ``app`` lazily so importing this module never needs a ``.env`` (uvicorn uses it)."""
    if name != "app":
        raise AttributeError(name)
    if name not in _apps:
        try:
            _apps[name] = create_app()
        except ConfigError as exc:
            print(f"alpaca-gatherer: {exc}", file=sys.stderr)
            raise SystemExit(1) from None
    return _apps[name]
