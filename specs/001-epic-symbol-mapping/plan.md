# Implementation Plan: Alpaca Gatherer — Epic ↔ Symbol Mapping Service

**Branch**: `001-epic-symbol-mapping` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-epic-symbol-mapping/spec.md`

## Summary

A FastAPI service, started with `uv run uvicorn`, that runs its own implementation of the
Capital.com → Alpaca instrument matching process and serves the resulting mapping. Capital.com data
comes from the collector through `to_collector_client`, and Alpaca assets, calendar and bars come
through an async httpx adapter that uses Fernet-encrypted credentials stored in MongoDB. A run
executes in the background, writes to a staging collection and swaps it into place atomically.
A MongoDB unique partial index makes sure only one run executes at a time. APScheduler rebuilds
the one scheduled job from the persisted schedule at startup. Startup recovery marks interrupted
runs as failed. All endpoints sit under `/api/v1` with plural resource names and RFC 7807 errors.

## Technical Context

**Language/Version**: Python 3.14 (uv-managed; research R1)

**Primary Dependencies**: FastAPI, uvicorn, pydantic v2, pydantic-settings, PyMongo (async API),
APScheduler 3.11, cryptography (Fernet), httpx, `to_collector_client`, tenacity, PyYAML

**Storage**: MongoDB (local standalone). Collections: mapping (live and staging), runs, schedule
and credentials (data-model.md)

**Testing**: pytest, pytest-asyncio, pytest-cov, respx, and a disposable local MongoDB for
integration tests (research R12)

**Target Platform**: Linux/macOS developer machine, run from a terminal; no containers

**Project Type**: web service (single backend project)

**Performance Goals**: lookups p95 < 1 s; run acknowledged < 1 s; full run < 30 min over about
3,600 epics and about 33,600 Alpaca assets (SC-001, SC-005)

**Constraints**: stateless process (state in MongoDB); no dependency on `alpacaMatcher/`;
credentials never in plain text at rest, in responses or in logs; collector concurrency ≤ 4; no
on-disk cache

**Scale/Scope**: one instance; about 3,600 mapping documents per snapshot; ≥ 50 run documents kept

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Pre-research | Post-design |
|---|---|---|---|
| I. Clean code & strict typing | mypy `--strict` and Ruff clean; no unjustified `Any`. Raw collector JSON (`dict[str, Any]`) is parsed into pydantic models at the adapter boundary | PASS | PASS |
| II. Python 3.14 & uv | `requires-python >=3.14`; uv only; `uv run` for app and tools. The brief's "3.12+" is resolved to 3.14 (R1) | PASS | PASS |
| III. Focused, modular library | One package `alpaca_gatherer`, layered modules, docstrings with examples on public APIs | PASS | PASS |
| IV. API-first, RESTful | Plural resources: `/thresholds`, `/runs`, `/schedules/current`, `/mappings`, `/credentials` under `/api/v1`; PUT replaces the schedule; OpenAPI written first (contracts/) | PASS (the brief's singular paths were replaced at the user's choice, R16) | PASS |
| V. RFC 7807 errors | Central problem-details mapping (R10, contracts/problems.md) | PASS | PASS |
| VI. Stateless services | All state in MongoDB; the run lock is a DB index (R6); the scheduler job is derived from the stored schedule (R7); the asyncio lock is only a fast path | PASS | PASS |
| VII. Service boundaries & clients | Collector only through `to_collector_client` (R2; replaces the brief's raw httpx); no access to other services' databases | PASS | PASS |
| VIII. Dependency inversion | `domain` has no I/O imports; ports (`typing.Protocol`) live in `application`; adapters live in `infrastructure`; wiring happens in `main.py` | PASS | PASS |
| IX. Testing & coverage | Integration tests for every repository; contract tests for both HTTP adapters; ≥ 80 % unit coverage on domain and application | PASS | PASS |
| Tech constraints: secrets | Fernet key and credentials only from `.env` and the DB; `.env` is git-ignored; `.env.example` is committed | PASS | PASS |

No violations, so Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-epic-symbol-mapping/
├── plan.md              # This file
├── research.md          # Phase 0: decisions R1–R17
├── data-model.md        # Phase 1: collections, fields, states, settings
├── quickstart.md        # Phase 1: setup and validation scenarios
├── contracts/
│   ├── openapi.yaml     # Phase 1: HTTP contract (/api/v1)
│   └── problems.md      # Phase 1: RFC 7807 problem catalog
├── checklists/requirements.md
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

The brief's suggested folders are mapped onto the constitution's layers (Principle VIII):
`matching/` → `domain/matching`, `scheduling/` → `domain/scheduling` + `infrastructure/scheduler`,
`runs/` → `application/runs`, `security/` → `infrastructure/security`, `clients/` →
`infrastructure/clients`, `db/` → `infrastructure/db`, `api/v1/` → `interface/api/v1`.

```text
pyproject.toml                 # uv project, ruff, mypy --strict, pytest config
uv.lock
.python-version                # 3.14
.env.example                   # every setting, commented
config/
└── thresholds.yaml            # default thresholds (research R9)
docs/
└── matching-process.md        # implemented algorithm, thresholds, statuses, limitations (FR-032)
README.md                      # uv sync, .env, Fernet key, local MongoDB, uv run uvicorn, trust note
scripts/                       # record_reference_window.py, convert_baseline.py, measure_lookups.py (tooling only)

src/alpaca_gatherer/
├── main.py                    # app factory, lifespan: settings → thresholds → Mongo/indexes →
│                              #   startup recovery → scheduler rebuild; dependency wiring
├── config.py                  # Settings (pydantic-settings) and threshold loader
├── logging_setup.py           # TIME_ZONE formatter, run_id context filter, redaction
├── domain/                    # pure, no I/O
│   ├── mapping.py             # InstrumentMapping, Candidate, Reason, MatchStatus, MatchType
│   ├── runs.py                # Run, RunStatus, RunTrigger, RunErrorCode, retention policy
│   ├── thresholds.py          # Thresholds value object (grouped)
│   ├── errors.py              # DomainError hierarchy (one per problem code)
│   ├── scheduling/
│   │   ├── definitions.py     # CronSchedule, RecurringSchedule, OneTimeSchedule, parsing/validation
│   │   └── rendering.py       # convert to a display timezone
│   └── matching/
│       ├── normalize.py       # symbol/epic aliasing, company-name normalization
│       ├── candidates.py      # exact → alias → name candidate generation
│       ├── window.py          # session selection, regular-session filter, bar alignment
│       ├── checks.py          # data, price, behavior (hourly/session), tradability
│       ├── classify.py        # per-epic status, reasons, symbol-conflict pass
│       └── universe.py        # catalog ∪ sweep filtering rules (SHARES, USD, US close hours)
├── application/
│   ├── ports.py               # Protocols: CapitalCatalogPort, AlpacaMarketPort, MappingRepository,
│   │                          #   RunRepository, ScheduleRepository, CredentialRepository,
│   │                          #   SecretCipher, JobScheduler, Clock
│   ├── runs/
│   │   ├── start_run.py       # acquire lock, create run, launch background execution
│   │   ├── execute_run.py     # orchestrate stages, staging write, swap, counts, prune
│   │   ├── recover.py         # startup recovery (FR-012b)
│   │   └── queries.py         # get run, list runs
│   ├── schedule.py            # get view, set/clear schedule, on-fire handler
│   ├── mappings.py            # lookup by epic or symbol
│   ├── credentials.py         # register, update
│   └── thresholds.py          # get thresholds
├── infrastructure/
│   ├── db/
│   │   ├── client.py          # AsyncMongoClient factory
│   │   ├── indexes.py         # index creation at startup
│   │   ├── mapping_repo.py    # live reads, staging writes, renameCollection swap, staging cleanup
│   │   ├── run_repo.py        # unique running index, list/paginate, prune
│   │   ├── schedule_repo.py
│   │   └── credential_repo.py
│   ├── clients/
│   │   ├── collector.py       # CollectorGateway over to_collector_client (to_thread + semaphore)
│   │   ├── alpaca.py          # AlpacaGateway (httpx async): assets, calendar, bars
│   │   └── retry.py           # tenacity policies
│   ├── security/fernet_cipher.py
│   └── scheduler/apscheduler_adapter.py   # AsyncIOScheduler job build/replace/remove, next fire time
└── interface/api/
    ├── problems.py            # RFC 7807 models and exception handlers
    ├── deps.py                # FastAPI dependencies (future auth dependency attaches here)
    └── v1/
        ├── router.py          # mounts the sub-routers under /api/v1
        ├── thresholds.py
        ├── runs.py
        ├── schedules.py
        ├── mappings.py
        ├── credentials.py
        └── schemas/           # request/response models, one module per resource:
                               #   mappings.py, credentials.py, runs.py, schedules.py, thresholds.py

tests/
├── conftest.py                # Mongo test DB fixture (MONGO_TEST_URL), app factory with fakes
├── fakes.py                   # in-memory port implementations
├── unit/{domain,application,infrastructure,interface}/
├── integration/               # repositories, swap, lock index, every endpoint
├── contract/                  # Alpaca and collector adapters with respx
├── golden/                    # matching over tests/fixtures/reference_window (SC-006)
├── fixtures/{alpaca,reference_window}/
└── test_no_reference_dependency.py   # FR-005 guard
```

**Structure Decision**: a single backend project in the uv `src` layout, with the package
`alpaca_gatherer` split into constitution layers. The empty `src/`, `tests/`, `config/` and `docs/`
folders already in the repository are used as shown. `alpacaMatcher/` is never imported or read.

## Key Flows

**Start run** (`POST /runs`): credentials exist? → asyncio lock → insert a `running` run (the unique
index rejects a second one → 409) → `asyncio.create_task(execute_run)` → 202.

**Execute run**: set the `run_id` context var → decrypt credentials → collector universe (catalogs +
sweep) → Alpaca assets and calendar → window ending at `started_at` → candidate generation → bars
(collector: 4 concurrent requests; Alpaca: 100 symbols per request) → checks → classify → conflict
pass → write staging → `renameCollection` swap → run `succeeded` with counts → prune history. Any
exception → drop staging → run `failed` with an `error.code` → prune.

**Scheduled fire**: the job calls the same start logic with `trigger=scheduled`. If a run is
already active, a `failed/skipped_concurrent_run` run is recorded instead. A one-time schedule
deletes itself after firing.

**Startup** (lifespan, in order): load and validate settings and thresholds (fail fast) → connect to
Mongo and ensure indexes → mark `running` runs as `failed/interrupted_by_restart` → drop
`*_staging_*` → clear a missed one-time schedule → rebuild the scheduler job → start the scheduler.
**Shutdown**: stop the scheduler, cancel the active run task (the next start records it as
interrupted), close clients.

## Complexity Tracking

No constitution violations to justify.
