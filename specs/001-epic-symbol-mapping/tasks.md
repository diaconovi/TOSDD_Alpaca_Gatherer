---

description: "Task list for Alpaca Gatherer — Epic ↔ Symbol Mapping Service"
---

# Tasks: Alpaca Gatherer — Epic ↔ Symbol Mapping Service

**Input**: Design documents from `specs/001-epic-symbol-mapping/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/openapi.yaml,
contracts/problems.md, quickstart.md

**Tests**: Included. Constitution Principle IX requires integration/contract tests for every
repository and HTTP client, plus ≥ 80 % unit coverage on `domain` and `application`; the plan brief
lists the required unit and integration tests. Write each story's tests first and confirm they fail.

**Organization**: Tasks are grouped by user story so each story can be implemented and tested on
its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story from spec.md (US1–US5)
- Package root: `src/alpaca_gatherer/`. Tests: `tests/`. All commands run through `uv run`.

## Conventions every task must follow

- Full type annotations; `uv run mypy` (strict) and `uv run ruff check` must stay clean.
- Public modules, classes and functions get docstrings, with a short `>>>` example where useful.
- `domain/` imports nothing from `application/`, `infrastructure/`, `interface/`, FastAPI, PyMongo,
  httpx or APScheduler. Ports are `typing.Protocol` classes in `application/ports.py`.
- All datetimes are timezone-aware UTC internally; convert only when building responses.
- Never log, return or put into an exception message the Alpaca key or secret.
- Nothing may import from, read from, or name the `alpacaMatcher/` folder.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization

- [X] T001 Create `pyproject.toml` at the repo root: project `alpaca-gatherer`, `requires-python = ">=3.14"`, hatchling build backend with the `src/alpaca_gatherer` package; add `.python-version` containing `3.14`
- [X] T002 Add runtime dependencies with `uv add fastapi "uvicorn[standard]" "pydantic>=2" pydantic-settings "pymongo>=4.13" "apscheduler>=3.11,<4" cryptography httpx tenacity pyyaml` and the collector client with `uv add "to_collector_client @ git+ssh://git@github.com/diaconovi/Trade_Ops_Library.git#subdirectory=packages/to_collector"`; commit `uv.lock` (research R2, R17)
- [X] T003 Add dev dependencies with `uv add --dev pytest pytest-asyncio pytest-cov respx mypy ruff types-pyyaml`
- [X] T004 [P] Configure Ruff (lint + format, line length 100, target py314) and mypy (`strict = true`, `files = ["src", "tests"]`, pydantic plugin) in `pyproject.toml`
- [X] T005 [P] Configure pytest and coverage in `pyproject.toml`: `asyncio_mode = "auto"`, `testpaths = ["tests"]`, markers `integration`, `contract`, `golden`; `[tool.coverage.run] source = ["alpaca_gatherer.domain", "alpaca_gatherer.application"]`, `[tool.coverage.report] fail_under = 80`; the gate command is `uv run pytest tests/unit --cov` and applies from the first story onward
- [X] T006 [P] Create the package skeleton with empty `__init__.py` files for `src/alpaca_gatherer/{domain,domain/scheduling,domain/matching,application,application/runs,infrastructure,infrastructure/db,infrastructure/clients,infrastructure/security,infrastructure/scheduler,interface,interface/api,interface/api/v1,interface/api/v1/schemas}/` per plan.md
- [X] T007 [P] Create `.env.example` at the repo root documenting every variable in data-model.md §6 with a comment each: `COLLECTOR_URL=http://localhost:8001`, `MONGO_URL=mongodb://localhost`, `MONGO_PORT=27017`, `MONGO_MAPPING_DB=`, `MONGO_MAPPING_COLLECTION=`, `LOGGING=INFO` (INFO | DEBUG | WARNING), `TIME_ZONE=America/Mexico_City` (logs and non-schedule output only), `FIELD_ENCRYPTION_KEY=` (Fernet.generate_key().decode()), `THRESHOLDS_FILE=config/thresholds.yaml`, `RUN_HISTORY_LIMIT=50`, `ALPACA_TRADING_URL=https://paper-api.alpaca.markets`, `ALPACA_DATA_URL=https://data.alpaca.markets`; make sure `.gitignore` ignores `.env`
- [X] T008 [P] Create `config/thresholds.yaml` with the defaults from research R9, grouped `candidates` (`name_ratio: 0.90`, `max_name_candidates: 3`), `window` (`sessions: 20`, `embargo_minutes: 20`, `min_bars: 60`, `feed: sip`), `price` (`price_tol_pct: 1.0`, `spread_mult: 0.5`), `behavior` (`corr_threshold: 0.70`, `dir_threshold: 0.75`, `min_sig_moves: 10`, `min_session_returns: 12`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Configuration, errors, logging, database access, app skeleton and test harness that
every story needs.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Tests for the foundation

- [X] T009 [P] Unit tests for settings in `tests/unit/infrastructure/test_config.py`: missing `FIELD_ENCRYPTION_KEY` or a non-Fernet value fails; `TIME_ZONE="Mars/Base"` fails; `LOGGING` outside `INFO | DEBUG | WARNING` fails; `RUN_HISTORY_LIMIT=49` fails ("≥ 50 (FR-012a minimum)"); `MONGO_MAPPING_COLLECTION` containing `$` or `.` fails; `COLLECTOR_URL` without host fails; the defaults (`MONGO_PORT=27017`, `LOGGING=INFO`, `TIME_ZONE=UTC`, `THRESHOLDS_FILE=config/thresholds.yaml`, `RUN_HISTORY_LIMIT=50`) apply
- [X] T010 [P] Unit tests for the threshold loader in `tests/unit/infrastructure/test_thresholds_loader.py`: a valid file loads into the four groups; a missing file, invalid YAML, an unknown key (`extra="forbid"`), a missing field and every out-of-range rule from research R9 (`0 < name_ratio ≤ 1`, `max_name_candidates ≥ 1`, `sessions ≥ 2`, `embargo_minutes ≥ 0`, `min_bars ≥ 2`, `feed` in `sip | iex`, `price_tol_pct > 0`, `spread_mult ≥ 0`, `−1 ≤ corr_threshold ≤ 1`, `0 ≤ dir_threshold ≤ 1`, `min_sig_moves ≥ 1`, `min_session_returns ≥ 1`) each raise an error naming the file and the field
- [X] T011 [P] Unit tests for problem details in `tests/unit/interface/test_problems.py`: each `DomainError` subclass maps to the status and `type` (`urn:alpaca-gatherer:problem:<code>`) in contracts/problems.md; request validation errors produce 422 `validation_error` with `errors: [{loc, msg}]`; an unexpected exception produces 500 `internal_error` without the exception text; the media type is `application/problem+json`
- [X] T012 [P] Unit tests for logging in `tests/unit/infrastructure/test_logging_setup.py`: timestamps are rendered in `TIME_ZONE`; `run_id` is injected from the context variable (`run_id=-` when unset); registered secret values are masked

### Implementation

- [X] T013 [P] Implement the `Thresholds` frozen value object with groups `CandidateThresholds`, `WindowThresholds`, `PriceThresholds`, `BehaviorThresholds` in `src/alpaca_gatherer/domain/thresholds.py` (plain frozen dataclasses, no pydantic in domain)
- [X] T014 [P] Implement the `DomainError` hierarchy in `src/alpaca_gatherer/domain/errors.py`, one class per code in contracts/problems.md: `RunInProgress(active_run_id)`, `CredentialsMissing`, `CredentialsExist`, `CredentialsNotFound`, `RunNotFound`, `InstrumentNotFound`, `MappingNotAvailable`, `ScheduleValidationError(field, message)`, `CredentialsUndecryptable`, `CollectorUnavailable`, `CollectorIncompleteData`, `AlpacaUnavailable`, `AlpacaAuthFailed`; each carries `code`, `title` and a safe `detail`
- [X] T015 [P] Implement `Clock` and the persistence/scheduler port `Protocol`s needed across stories (`Clock`, `MappingRepository`, `RunRepository`, `ScheduleRepository`, `CredentialRepository`, `SecretCipher`, `JobScheduler`, `CapitalCatalogPort`, `AlpacaMarketPort`) with method signatures only in `src/alpaca_gatherer/application/ports.py`; also add `SystemClock` in `src/alpaca_gatherer/infrastructure/clock.py`
- [X] T016 Implement `Settings` (pydantic-settings, reads `.env`) with every variable, default and validation in data-model.md §6, plus a `collector_endpoint` property that parses `COLLECTOR_URL` into `(scheme, host, port)`, and `load_thresholds(path) -> Thresholds` (PyYAML `safe_load` → pydantic model with `extra="forbid"` → domain `Thresholds`) in `src/alpaca_gatherer/config.py` (makes T009, T010 pass)
- [X] T017 [P] Implement logging setup in `src/alpaca_gatherer/logging_setup.py`: a `Formatter` whose `formatTime` uses `ZoneInfo(TIME_ZONE)`, a `ContextVar[str | None]` named `current_run_id` with a `logging.Filter` that adds `run_id`, a redaction filter with `register_secret(value)`, and `configure_logging(level, tz)` (makes T012 pass)
- [X] T018 [P] Implement RFC 7807 support in `src/alpaca_gatherer/interface/api/problems.py`: a `Problem` response model, `register_problem_handlers(app)` for `DomainError`, `RequestValidationError`, `HTTPException` and a fallback `Exception` handler, using the status table in contracts/problems.md (makes T011 pass)
- [X] T019 Implement the async MongoDB client factory (`AsyncMongoClient` from `MONGO_URL` + `MONGO_PORT`) and a `Collections` helper that names `M`, `M_runs`, `M_schedule`, `M_credentials` and `M_staging_<run_id>` from `MONGO_MAPPING_COLLECTION` in `src/alpaca_gatherer/infrastructure/db/client.py`
- [X] T020 Implement `ensure_indexes(db, collections)` in `src/alpaca_gatherer/infrastructure/db/indexes.py`: on `M` a unique index on `capital_epic` and a unique partial index on `alpaca_symbol` with `partialFilterExpression {status: "matched"}`; on `M_runs` a unique partial index on `status` with `partialFilterExpression {status: "running"}` and an index `started_at: -1`; expose `create_mapping_indexes(collection)` so staging collections get the same mapping indexes
- [X] T021 Implement the FastAPI dependency container in `src/alpaca_gatherer/interface/api/deps.py` (typed accessors that read wired services from `app.state`; this is where a future auth dependency attaches — FR-027) and the empty v1 router mounted at `/api/v1` in `src/alpaca_gatherer/interface/api/v1/router.py`
- [X] T022 Implement the app factory and lifespan in `src/alpaca_gatherer/main.py`: `create_app(settings=None, overrides=None)` loads settings and thresholds (fail fast with a message naming the variable or file), configures logging, connects to Mongo, runs `ensure_indexes`, registers problem handlers, includes the v1 router, enables OpenAPI docs, and exposes `app = create_app()`; leave clearly marked lifespan hooks for startup recovery and the scheduler (filled in US3/US4)
- [X] T023 [P] Create the test harness in `tests/conftest.py`: a session-scoped disposable Mongo database from `MONGO_TEST_URL` (unique database name per session, dropped at the end; if `MONGO_TEST_URL` is unset or unreachable, the session **fails** with a message naming the variable, unless pytest runs with `--allow-no-mongo`, which skips only the `integration` tests and prints a warning; register the option in `tests/conftest.py` with `pytest_addoption`), a test `Settings` factory with a generated Fernet key and a temp thresholds file, an `httpx.AsyncClient(transport=ASGITransport(app))` fixture, and a `FrozenClock`
- [X] T024 [P] Create in-memory fakes of every port from T015 in `tests/fakes.py`
- [X] T025 [P] Add the FR-005 guard test in `tests/test_no_reference_dependency.py`: scan every file under `src/`, `config/` and `tests/` (except this test) and fail if any contains `alpacaMatcher`, `match_instruments` or `alpaca-keys`

**Checkpoint**: `uv run pytest tests/unit` passes; `uv run uvicorn alpaca_gatherer.main:app` starts with a valid `.env` and exits with a clear message for each bad setting.

---

## Phase 3: User Story 1 - Translate an instrument between brokers (Priority: P1) 🎯 MVP

**Goal**: Consumers look up a stored mapping by exactly one of `capital_epic` or `alpaca_symbol`.

**Independent Test**: Seed the mapping collection with matched, ambiguous and unmatched documents,
then exercise `GET /api/v1/mappings` (spec US1 scenarios 1–5).

### Tests for User Story 1 ⚠️

- [X] T026 [P] [US1] Unit tests for mapping invariants in `tests/unit/domain/test_mapping.py`: "`status = matched` ⇒ `alpaca_symbol` and `match_type` are set, `reason` is null"; "`status ≠ matched` ⇒ `alpaca_symbol` and `match_type` are null and `reason` is set"; `ambiguous` reason codes limited to `multiple_candidates`, `name_only_with_unchecked_identifier`, `symbol_conflict`; `unmatched` codes limited to `not_listed_on_alpaca`, `not_tradable`, `insufficient_data`, `failed_price_check`, `failed_behavior_check`
- [X] T027 [P] [US1] Unit tests for the lookup use case in `tests/unit/application/test_mappings.py` with fakes: both or neither parameter → validation error; epic lookup returns any status; ambiguous epic returns `alpaca_symbol: None` plus its candidates; symbol lookup only matches `status = matched`; a symbol that is only an ambiguous candidate → `InstrumentNotFound`; unknown epic → `InstrumentNotFound`; empty or missing mapping → `MappingNotAvailable`
- [X] T028 [P] [US1] Integration tests for the mapping repository reads in `tests/integration/test_mapping_repo_read.py` against real Mongo: find by epic, find by matched symbol, the unique partial index rejects a second `matched` document with the same `alpaca_symbol` but allows two ambiguous documents listing the same candidate, `has_snapshot()` is false when the collection is absent
- [X] T029 [P] [US1] Integration tests for `GET /api/v1/mappings` in `tests/integration/test_api_mappings.py`: 200 for matched (by epic and by symbol, pointing at each other), ambiguous and unmatched epics; 422 `validation_error` for both/neither/empty parameters; 404 `instrument_not_found`; 404 `mapping_not_available` before any snapshot; response shape matches the `Mapping` schema in contracts/openapi.yaml

### Implementation for User Story 1

- [X] T030 [P] [US1] Implement `MatchStatus` (`matched | ambiguous | unmatched`), `MatchType` (`exact | alias`), `CandidateKind` (`exact | alias | name`), `Reason(code, detail)`, `Candidate` and `InstrumentMapping` with invariant validation in `src/alpaca_gatherer/domain/mapping.py`, following the fields in data-model.md §1 (makes T026 pass)
- [X] T031 [US1] Implement the read side of `MongoMappingRepository` (`find_by_epic`, `find_matched_by_symbol`, `has_snapshot`) with BSON ↔ domain conversion in `src/alpaca_gatherer/infrastructure/db/mapping_repo.py` (makes T028 pass)
- [X] T032 [US1] Implement `LookupMapping` in `src/alpaca_gatherer/application/mappings.py` with the lookup rules in data-model.md §1 (makes T027 pass)
- [X] T033 [P] [US1] Add `MappingResponse`, `CandidateResponse` and `ReasonResponse` models matching the `Mapping` schema in contracts/openapi.yaml to `src/alpaca_gatherer/interface/api/v1/schemas/mappings.py`
- [X] T034 [US1] Implement `GET /mappings` in `src/alpaca_gatherer/interface/api/v1/mappings.py` (query params `capital_epic`, `alpaca_symbol` with `minLength: 1`; exactly-one check → 422), include it in the v1 router, and wire `LookupMapping` in `main.py` (makes T029 pass)

**Checkpoint**: Lookups work against a seeded database (quickstart scenarios 11–13). `uv run pytest tests/unit --cov` passes the 80 % gate.

---

## Phase 4: User Story 2 - Register and maintain Alpaca credentials (Priority: P1)

**Goal**: Operators register and update Alpaca credentials. Only ciphertext is stored, and nothing
reveals the plain values.

**Independent Test**: Register, register again, update, update-before-register, then inspect the
credentials collection and logs (spec US2 scenarios 1–5).

### Tests for User Story 2 ⚠️

- [X] T035 [P] [US2] Unit tests for the Fernet cipher in `tests/unit/infrastructure/test_fernet_cipher.py`: encrypt/decrypt round trip; the ciphertext does not contain the plain text; decrypting with a different key raises a domain-level `CredentialsUndecryptable` error
- [X] T036 [P] [US2] Unit tests for the credential use cases in `tests/unit/application/test_credentials.py`: register stores two ciphertexts plus `created_at`/`updated_at`; a second register raises `CredentialsExist`; update before register raises `CredentialsNotFound`; update overwrites without decrypting the old values; `load_plain()` returns `None` when none are registered
- [X] T037 [P] [US2] Integration tests for the credential repository in `tests/integration/test_credential_repo.py`: insert with `_id: "alpaca"`; a duplicate insert raises `CredentialsExist`; `update_one` with `matched_count = 0` raises `CredentialsNotFound`; stored fields are exactly `api_key_enc`, `api_secret_enc`, `created_at`, `updated_at`
- [X] T038 [P] [US2] Integration tests for `/api/v1/credentials` in `tests/integration/test_api_credentials.py`: POST → 201 with empty body; POST again → 409 `credentials_exist`; PATCH → 204; PATCH before POST → 404 `credentials_not_found`; missing or empty `api_key`/`api_secret` → 422; extra fields → 422; the raw Mongo document and captured logs contain neither plain value (SC-003)

### Implementation for User Story 2

- [X] T039 [P] [US2] Implement `FernetCipher` (implements `SecretCipher`) in `src/alpaca_gatherer/infrastructure/security/fernet_cipher.py`, mapping `InvalidToken` to `CredentialsUndecryptable` (from T014) (makes T035 pass)
- [X] T040 [US2] Implement `MongoCredentialRepository` in `src/alpaca_gatherer/infrastructure/db/credential_repo.py` per data-model.md §4 (makes T037 pass)
- [X] T041 [US2] Implement `RegisterCredentials`, `UpdateCredentials` and `CredentialsProvider.load_plain()` (decrypts only on demand and registers both values with the logging redaction filter) in `src/alpaca_gatherer/application/credentials.py` (makes T036 pass)
- [X] T042 [P] [US2] Add `CredentialsRequest` (`api_key`, `api_secret`: `minLength: 1`, `extra="forbid"`, both `SecretStr`) to `src/alpaca_gatherer/interface/api/v1/schemas/credentials.py`
- [X] T043 [US2] Implement `POST /credentials` (201, empty body) and `PATCH /credentials` (204) in `src/alpaca_gatherer/interface/api/v1/credentials.py`, include it in the router and wire it in `main.py` (makes T038 pass)

**Checkpoint**: Quickstart scenarios 4–7 pass. `uv run pytest tests/unit --cov` passes the 80 % gate.

---

## Phase 5: User Story 3 - Run matching on demand (Priority: P2)

**Goal**: `POST /api/v1/runs` starts a full background run that rebuilds the mapping atomically.
Runs can be inspected and listed, at most one runs at a time, and startup recovers interrupted runs.

**Independent Test**: With credentials registered and the collector and Alpaca stubbed, trigger a
run, check the immediate 202, wait for `succeeded`, verify the mapping and run documents; repeat
with failures (spec US3 scenarios 1–6).

**Depends on**: US1 (mapping model and repository), US2 (credential provider).

### Tests for User Story 3 ⚠️

- [X] T044 [P] [US3] Unit tests for normalization and aliasing in `tests/unit/domain/matching/test_normalize.py`: `BRK.B` = `BRK/B` = `BRKb`; the lowercase `us`/` US` suffix is stripped (`AXONus`, `NLOP US`); a trailing lowercase letter becomes a share class (`HEIa` → `HEI.A`); `/` becomes `.` (`GME/WS` → `GME.WS`); class root (`BRK` → `BRK.A`, `BRK.B`); epic spellings derived from symbols for the sweep (`BRK.B` → `BRKB`, `BRKBUS`); name normalization drops legal suffixes and share-class words
- [X] T045 [P] [US3] Unit tests for candidate generation in `tests/unit/domain/matching/test_candidates.py`: exact candidate when symbol == epic; alias candidates from epic and Capital.com `symbol`; the name fallback is used only when no identifier candidate passes the price check, accepts `difflib` ratio ≥ `name_ratio` or full token containment, and caps at `max_name_candidates`; inactive and non-tradable assets are kept as candidates
- [X] T046 [P] [US3] Unit tests for the window in `tests/unit/domain/matching/test_window.py`: picks the last `sessions` complete sessions ending ≥ `embargo_minutes` before `price_window_end`; the query range is `[floor(first open), last close]`; only bars starting in `[floor(open), close)` are kept, including a half day and a DST change; bars are inner-joined on identical UTC timestamps
- [X] T047 [P] [US3] Unit tests for the checks in `tests/unit/domain/matching/test_checks.py`: fewer than `min_bars` aligned bars → `insufficient_data` with both bar counts; `price_diff_pct` = median of `|cap_mid − alpaca_close| / alpaca_close × 100`; tolerance = `price_tol_pct + spread_mult × median(cap_spread / cap_mid) × 100`; hourly pass needs ≥ `min_sig_moves` significant moves (above the median relative spread) with correlation ≥ `corr_threshold` and direction ≥ `dir_threshold`; otherwise session fallback with ≥ `min_session_returns`; otherwise `failed_behavior_check` or `insufficient_data`; the reported metrics come from the deciding horizon; tradability is checked last
- [X] T048 [P] [US3] Unit tests for classification in `tests/unit/domain/matching/test_classify.py`: exact pass → `matched/exact` even if an alias also passes; one non-exact pass → `matched/alias`; several non-exact passes → `ambiguous/multiple_candidates`; name-only pass with an identifier candidate lacking data → `ambiguous/name_only_with_unchecked_identifier`; nothing passes → `unmatched` with the reason of the furthest candidate (behavior > price > data; the exact candidate is preferred when nothing got past price); two epics matched to one symbol → both `ambiguous/symbol_conflict` listing each other (research R15)
- [X] T049 [P] [US3] Unit tests for universe filtering in `tests/unit/domain/matching/test_universe.py`: catalog union of the four US catalogs keeps only `SHARES`; swept instruments are kept only if `SHARES`, priced in `USD`, and their weekday hours end at 20:00 or 21:00 UTC or run 24 h; duplicates across sources are merged with `source` = `catalog` taking precedence
- [X] T050 [P] [US3] Unit tests for run domain rules in `tests/unit/domain/test_runs.py`: allowed transitions per the state diagram in data-model.md §2 (`running → succeeded | failed` only; terminal states are final); the retention policy keeps the newest `RUN_HISTORY_LIMIT` executed terminal runs plus the newest 20 `skipped_concurrent_run` records, and never selects a `running` run for deletion
- [X] T051 [P] [US3] Unit tests for the run use cases in `tests/unit/application/test_runs.py` with fakes: start without credentials raises `CredentialsMissing`; start while running raises `RunInProgress(active_run_id)`; a successful execution writes staging, swaps, sets `succeeded` with `counts` (`matched`, `ambiguous`, `unmatched`, `total`, `by_reason`), and `price_window_end == started_at`; collector connection failure → `failed/collector_unavailable` and the live mapping is untouched; incomplete collector data → `failed/collector_incomplete_data`; Alpaca 401/403 → `failed/alpaca_auth_failed`; undecryptable credentials → `failed/credentials_undecryptable`; pruning runs after every terminal state; every log record during execution carries the `run_id`
- [X] T052 [P] [US3] Unit tests for startup recovery in `tests/unit/application/test_recover.py`: every `running` run becomes `failed` with `error.code = "interrupted_by_restart"`, detail "interrupted by service restart" and `finished_at = now`; staging collections are dropped; the live mapping is not touched; no run is started
- [X] T053 [P] [US3] Contract tests for `CollectorGateway` in `tests/contract/test_collector_gateway.py` using `respx` on the collector's httpx calls: catalog discovery and the four US catalogs; `search_markets` batches of 50 with bisection on HTTP 400; `get_prices` with `Resolution.HOUR` and `from_`/`to`; a 404 on prices means "no history" (not retried); connection errors, 5xx and 429 are retried 5 times and then raise `CollectorUnavailable`; at most 4 concurrent price calls
- [X] T054 [P] [US3] Contract tests for `AlpacaGateway` in `tests/contract/test_alpaca_gateway.py` using `respx`: `GET /v2/assets?asset_class=us_equity` (all statuses kept), `GET /v2/calendar`, `GET /v2/stocks/bars` with `timeframe=1Hour`, `adjustment=raw`, `feed` from thresholds, 100 symbols per request and `next_page_token` pagination; the `APCA-API-KEY-ID`/`APCA-API-SECRET-KEY` headers are sent but never logged; 401/403 → `AlpacaAuthFailed`; retries on 429/5xx/connection errors
- [X] T055 [P] [US3] Integration tests for the mapping repository writes in `tests/integration/test_mapping_repo_swap.py`: `write_staging(run_id, records)` creates `M_staging_<run_id>` with the mapping indexes; `swap(run_id)` replaces `M` via `renameCollection(dropTarget=True)` so a concurrent reader sees only the whole old or whole new snapshot; `drop_staging(run_id)` and `drop_all_staging()` remove leftovers
- [X] T056 [P] [US3] Integration tests for the run repository in `tests/integration/test_run_repo.py`: inserting a second `running` run raises `RunInProgress` through the unique partial index; `get`, `list(limit, offset)` newest first with `total`; `mark_running_as_interrupted(now)`; `prune(limit, skip_limit=20)` applies both retention pools independently and never deletes a running run; 30 skip records do not evict any of 50 executed runs; `latest_succeeded()`
- [X] T057 [P] [US3] Integration tests for the runs API in `tests/integration/test_api_runs.py` with fake gateways: `POST /api/v1/runs` → 202 `{run_id, status: "running", started_at}` plus a `Location` header; a second POST while running → 409 `run_in_progress` with `active_run_id`; POST without credentials → 409 `credentials_missing`; `GET /runs/{run_id}` returns the `Run` schema and reaches `succeeded`; unknown id → 404 `run_not_found`; `GET /runs?limit=&offset=` (`limit` 1–50, default 20) is newest first, and out-of-range values → 422; a failing collector leaves earlier lookups unchanged (SC-008); with a fake collector that sleeps 5 s per call, `POST /api/v1/runs` still returns 202 in under 1 s, measured with `time.perf_counter()`, which proves the run does not block the request (SC-005)
- [X] T058 [P] [US3] Golden test in `tests/golden/test_reference_window.py`: run the pure matching pipeline over the committed fixtures in `tests/fixtures/reference_window/` (universe, assets, calendar and bars as JSON) and compare `status`, `match_type` and `alpaca_symbol` per epic with `expected_mapping.json`, over the epics present in both; require ≥ 99 % agreement (SC-006) and list every difference in the failure message; report epics present on only one side separately (universe churn) without failing

### Implementation for User Story 3

- [X] T059 [P] [US3] Implement `Run`, `RunStatus` (`running | succeeded | failed`), `RunTrigger` (`manual | scheduled`), `RunErrorCode` (`collector_unavailable`, `collector_incomplete_data`, `alpaca_unavailable`, `alpaca_auth_failed`, `credentials_missing`, `credentials_undecryptable`, `skipped_concurrent_run`, `interrupted_by_restart`, `internal_error`), `RunCounts`, the transition rules and `select_runs_to_prune(runs, limit, skip_limit=20)` in `src/alpaca_gatherer/domain/runs.py` (makes T050 pass)
- [X] T060 [P] [US3] Implement the market-data value types the matching domain consumes (`CapitalInstrument`, `AlpacaAsset`, `Session`, `CapitalBar` with bid/ask close, `AlpacaBar`) in `src/alpaca_gatherer/domain/matching/models.py`
- [X] T061 [P] [US3] Implement normalization and aliasing in `src/alpaca_gatherer/domain/matching/normalize.py` (makes T044 pass)
- [X] T062 [P] [US3] Implement universe filtering and merging in `src/alpaca_gatherer/domain/matching/universe.py` (makes T049 pass)
- [X] T063 [P] [US3] Implement session selection, regular-session filtering and bar alignment in `src/alpaca_gatherer/domain/matching/window.py` (makes T046 pass)
- [X] T064 [US3] Implement candidate generation in `src/alpaca_gatherer/domain/matching/candidates.py` using `normalize.py` (makes T045 pass)
- [X] T065 [US3] Implement the data, price, behavior (hourly and session horizons) and tradability checks in `src/alpaca_gatherer/domain/matching/checks.py`, in the order data → price → behavior → tradability (makes T047 pass)
- [X] T066 [US3] Implement per-epic classification, reason selection and the symbol-conflict pass in `src/alpaca_gatherer/domain/matching/classify.py`, producing `InstrumentMapping` records (makes T048 pass)
- [X] T067 [US3] Implement the pure pipeline `match_universe(universe, assets, sessions, bars_by_epic, bars_by_symbol, thresholds) -> list[InstrumentMapping]` plus `name_candidates_needed(...)` (the second-pass request for name candidates' bars) in `src/alpaca_gatherer/domain/matching/pipeline.py`
- [X] T068 [P] [US3] Implement tenacity retry policies (exponential backoff with jitter, 5 attempts, on connection errors, HTTP 5xx and 429) in `src/alpaca_gatherer/infrastructure/clients/retry.py`
- [X] T069 [US3] Implement `CollectorGateway` (implements `CapitalCatalogPort`) over `to_collector_client.CollectorClient(host, port, scheme=…)` in `src/alpaca_gatherer/infrastructure/clients/collector.py`: every call through `asyncio.to_thread` under a semaphore of 4, catalog union, epic sweep in batches of 50 with bisection on 400, hourly prices, raw JSON parsed into the domain types, and the collector exceptions mapped to `CollectorUnavailable` or `CollectorIncompleteData` (makes T053 pass)
- [X] T070 [US3] Implement `AlpacaGateway` (implements `AlpacaMarketPort`) with `httpx.AsyncClient` against `ALPACA_TRADING_URL` and `ALPACA_DATA_URL` in `src/alpaca_gatherer/infrastructure/clients/alpaca.py`, with pydantic response models, pagination, 100 symbols per bars request, and `AlpacaAuthFailed`/`AlpacaUnavailable` mapping (makes T054 pass)
- [X] T071 [US3] Add the write side to `MongoMappingRepository`: `write_staging`, `swap` (`renameCollection` with `dropTarget=True`), `drop_staging`, `drop_all_staging` in `src/alpaca_gatherer/infrastructure/db/mapping_repo.py` (makes T055 pass)
- [X] T072 [US3] Implement `MongoRunRepository` in `src/alpaca_gatherer/infrastructure/db/run_repo.py`: `insert_running` (maps `DuplicateKeyError` to `RunInProgress` with the active id), `insert_terminal`, `finish`, `get`, `list`, `count`, `active`, `latest_succeeded`, `mark_running_as_interrupted`, `prune(limit, skip_limit=20)` (makes T056 pass)
- [X] T073 [US3] Implement `StartRun` in `src/alpaca_gatherer/application/runs/start_run.py`: check credentials → `asyncio.Lock` fast path → `insert_running` (`price_window_end = started_at`, thresholds snapshot) → launch `ExecuteRun` with `asyncio.create_task` and keep a reference to the task; for `trigger=scheduled`, catch `RunInProgress` and record `insert_terminal(status=failed, error.code="skipped_concurrent_run", detail naming the active run)` instead of raising
- [X] T074 [US3] Implement `ExecuteRun` in `src/alpaca_gatherer/application/runs/execute_run.py`: set `current_run_id`, decrypt credentials, fetch universe, assets and calendar, build the window, fetch bars, call `match_universe`, write staging, swap, finish as `succeeded` with counts; on any error drop staging and finish as `failed` with the mapped `RunErrorCode` and a safe detail; always prune afterwards (makes T051 pass)
- [X] T075 [P] [US3] Implement `GetRun` and `ListRuns` in `src/alpaca_gatherer/application/runs/queries.py`
- [X] T076 [US3] Implement `RecoverOnStartup` in `src/alpaca_gatherer/application/runs/recover.py` (makes T052 pass)
- [X] T077 [P] [US3] Add `RunAcceptedResponse`, `RunResponse`, `RunCountsResponse`, `RunErrorResponse` and `RunPageResponse` matching contracts/openapi.yaml to `src/alpaca_gatherer/interface/api/v1/schemas/runs.py`
- [X] T078 [US3] Implement `POST /runs` (202 + `Location`), `GET /runs` (`limit` 1–50, default 20; `offset` ≥ 0, default 0) and `GET /runs/{run_id}` in `src/alpaca_gatherer/interface/api/v1/runs.py`, and include it in the router (makes T057 pass)
- [X] T079 [US3] Wire the gateways, repositories and run use cases in `main.py`; in the lifespan run `RecoverOnStartup` right after `ensure_indexes` and before the scheduler hook; on shutdown cancel the active run task and close the httpx and collector clients
- [X] T080 [US3] Create the golden fixtures in `tests/fixtures/reference_window/`, in one session on the same day: (1) pick a fixed past `price_window_end` (UTC, outside market hours); (2) run `scripts/record_reference_window.py --end <ts>`, which uses this service's `CollectorGateway` and `AlpacaGateway` only and writes `universe.json`, `assets.json`, `calendar.json`, `capital_bars/*.json`, `alpaca_bars/*.json`; (3) manually run the prototype outside this repository with the same `--end <ts>` and default thresholds; (4) convert its `mapping.csv` with `scripts/convert_baseline.py <csv>` into `expected_mapping.json`, mapping `matched_exact` → `{status: matched, match_type: exact}` and `matched_alias` → `{status: matched, match_type: alias}` and keeping `ambiguous`/`unmatched` and the reason code; (5) write `README.md` with the timestamp, prototype commit, epic counts and refresh steps, without naming the prototype folder or its script (so T025 still passes) (makes T058 runnable)

**Checkpoint**: Quickstart scenarios 3, 8–13, 18 and 19 pass. `uv run pytest tests/unit --cov` passes the 80 % gate.

---

## Phase 6: User Story 4 - Schedule automatic matching runs (Priority: P2)

**Goal**: Operators set, view and clear a schedule in cron, recurring or one-time form, with an
optional IANA timezone. The schedule survives restarts.

**Independent Test**: PUT each format, GET the view, restart, and confirm persistence and the next
run time (spec US4 scenarios 1–7).

**Depends on**: US3 (`StartRun` with `trigger=scheduled`; `latest_succeeded` for `last_run`).

### Tests for User Story 4 ⚠️

- [X] T081 [P] [US4] Unit tests for schedule parsing in `tests/unit/domain/scheduling/test_definitions.py`: exactly one of `cron` / `schedule` (mixed → error on the field); `schedule` with both `date` and `day`/`time` → error; `day` accepts `mon`…`sun`, ascending ranges (`mon-fri`) and comma lists, and rejects `mon-xyz`, `fri-mon` and empty values; `time` must be `HH:MM` 00:00–23:59 (`25:00` and `7:5` rejected); `date` must be timezone-aware and in the future; `timezone` must resolve with `ZoneInfo` (`Mars/Base` rejected); missing timezone → `UTC`; invalid cron (`61 * * * *`) rejected; `schedule: null` → clear
- [X] T082 [P] [US4] Unit tests for rendering in `tests/unit/domain/scheduling/test_rendering.py`: `next_run`/`last_run` are rendered in the schedule's timezone; with no schedule, `last_run` is rendered in UTC and `timezone` is `"UTC"`; a recurring 18:00 `America/New_York` schedule across the November DST change gives `-04:00` before and `-05:00` after; a one-time date keeps its instant whatever the display timezone
- [X] T083 [P] [US4] Unit tests for the schedule use cases in `tests/unit/application/test_schedule.py` with fakes: set persists the definition and replaces the job, returning the applied schedule and next run; invalid input never touches the repository or the scheduler; clear deletes the document and removes the job; on fire, a one-time schedule deletes itself; at startup a one-time schedule in the past is cleared and logged as missed and not run; rebuild from the stored document recreates the job
- [X] T084 [P] [US4] Integration tests for the schedule repository in `tests/integration/test_schedule_repo.py`: a single document `_id: "schedule"` with `kind`, `cron`, `day`, `time`, `date` (UTC), `timezone`, `updated_at`; upsert replaces it; delete removes it
- [X] T085 [P] [US4] Integration tests for the APScheduler adapter in `tests/integration/test_apscheduler_adapter.py`: a cron, recurring and one-time trigger each produce the expected next fire time for a frozen "now"; replacing keeps exactly one job `matching-run`; the job options are `coalesce=True`, `max_instances=1`, `misfire_grace_time=60`
- [X] T086 [P] [US4] Integration tests for the schedule API in `tests/integration/test_api_schedule.py`: `PUT /api/v1/schedules/current` with each example in contracts/openapi.yaml → 200 with `schedule`, `next_run`, `last_run`, `timezone`; each invalid case from quickstart scenario 16 → 422 `validation_error` naming the field, and a following `GET` is unchanged; `schedule: null` → `schedule: null`, `next_run: null`, `timezone: "UTC"`; recreating the app against the same database restores the schedule and `last_run` (SC-007)

### Implementation for User Story 4

- [X] T087 [P] [US4] Implement `CronSchedule`, `RecurringSchedule`, `OneTimeSchedule`, `ScheduleDefinition` (union), `parse_schedule_request(payload, now) -> ScheduleDefinition | None` with field-named `ScheduleValidationError`s in `src/alpaca_gatherer/domain/scheduling/definitions.py`; validate cron syntax through a `CronValidator` port passed in, so the domain does not import APScheduler (makes T081 pass)
- [X] T088 [P] [US4] Implement display conversion (`to_display(dt, tz)`) and the schedule view assembly in `src/alpaca_gatherer/domain/scheduling/rendering.py` (makes T082 pass)
- [X] T089 [US4] Implement `MongoScheduleRepository` (`get`, `put`, `delete`) per data-model.md §3 in `src/alpaca_gatherer/infrastructure/db/schedule_repo.py` (makes T084 pass)
- [X] T090 [US4] Implement `ApschedulerJobScheduler` (implements `JobScheduler` and `CronValidator`) in `src/alpaca_gatherer/infrastructure/scheduler/apscheduler_adapter.py`: `AsyncIOScheduler`; build `CronTrigger.from_crontab(expr, timezone=ZoneInfo(tz))`, `CronTrigger(day_of_week=day, hour=h, minute=m, timezone=…)` or `DateTrigger(run_date=…)`; `replace_job`, `remove_job`, `next_fire_time(definition, now)`, `start`, `shutdown` (makes T085 pass)
- [X] T091 [US4] Implement `GetSchedule`, `SetSchedule`, `OnScheduledFire` (calls `StartRun` with `trigger=scheduled`, deletes a one-time schedule after firing) and `RestoreScheduleOnStartup` (clears a missed one-time schedule, rebuilds the job) in `src/alpaca_gatherer/application/schedule.py` (makes T083 pass)
- [X] T092 [P] [US4] Add `ScheduleRequest` (`extra="forbid"`; `cron`, `schedule`, `timezone`) and `ScheduleViewResponse` matching contracts/openapi.yaml to `src/alpaca_gatherer/interface/api/v1/schemas/schedules.py`
- [X] T093 [US4] Implement `GET /schedules/current` and `PUT /schedules/current` in `src/alpaca_gatherer/interface/api/v1/schedules.py` and include it in the router (makes T086 pass)
- [X] T094 [US4] Wire scheduling in `main.py`: create the scheduler, run `RestoreScheduleOnStartup` after `RecoverOnStartup`, start the scheduler, and shut it down first on exit

**Checkpoint**: Quickstart scenarios 14–17 and 20 pass. `uv run pytest tests/unit --cov` passes the 80 % gate.

---

## Phase 7: User Story 5 - Inspect matching thresholds (Priority: P3)

**Goal**: Operators read the thresholds in use, grouped by matching stage.

**Independent Test**: Start with a known thresholds file and compare `GET /api/v1/thresholds` with
it (spec US5 scenarios 1–2; scenario 2 is covered by T010 and T016).

### Tests for User Story 5 ⚠️

- [X] T095 [P] [US5] Integration test in `tests/integration/test_api_thresholds.py`: `GET /api/v1/thresholds` returns exactly the values of the test thresholds file under `candidates`, `window`, `price`, `behavior` (the `Thresholds` schema in contracts/openapi.yaml)

### Implementation for User Story 5

- [X] T096 [P] [US5] Implement `GetThresholds` in `src/alpaca_gatherer/application/thresholds.py` and add `ThresholdsResponse` to `src/alpaca_gatherer/interface/api/v1/schemas/thresholds.py`
- [X] T097 [US5] Implement `GET /thresholds` in `src/alpaca_gatherer/interface/api/v1/thresholds.py`, include it in the router and wire it in `main.py` (makes T095 pass)

**Checkpoint**: Quickstart scenario 2 passes. `uv run pytest tests/unit --cov` passes the 80 % gate.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T098 [P] Write `docs/matching-process.md` (FR-032): the implemented stages (universe catalogs + sweep, Alpaca assets, exact → alias → name candidates, window and alignment, price check, behavior check, classification, symbol-conflict pass), every threshold with its default and meaning, the statuses `matched` (`exact`/`alias`), `ambiguous` and `unmatched` with every reason code, retries and rate limits, the absence of a local cache, and known limitations; adapted from the prototype documentation and checked against this code
- [X] T099 [P] Write `README.md`: `uv sync`, copying `.env.example` to `.env`, generating the Fernet key, starting a local MongoDB from a terminal, `uv run uvicorn alpaca_gatherer.main:app --host 127.0.0.1 --port 8002`, the API overview and `/docs`, and the trust note (no authentication; internal network only; single instance — a schedule change reaches other instances only on restart)
- [X] T100 [P] Add an OpenAPI drift test in `tests/contract/test_openapi_contract.py` that compares the app's generated paths, methods, status codes and schema field names with `specs/001-epic-symbol-mapping/contracts/openapi.yaml`
- [X] T101 [P] Add a secret-leak test in `tests/integration/test_no_secret_leak.py`: register credentials, run a stubbed run that fails and one that succeeds, and assert that neither plain value appears in any response body, captured log record or Mongo document (SC-003)
- [X] T101a [P] Add `scripts/measure_lookups.py`: against a running service with a full snapshot, issue 200 `GET /api/v1/mappings` requests (100 random epics, 100 random matched symbols, read from the database), print p50/p95/max, and exit non-zero if p95 ≥ 1 s (SC-001)
- [X] T102 Confirm the coverage gate from T005 passes on the full code base, document it in `README.md`, and add unit tests in `tests/unit/` for any module below 80 %
- [X] T103 Run `uv run ruff check .`, `uv run ruff format --check .` and `uv run mypy`, and fix every finding
- [X] T104 With `alpacaMatcher/` moved out of the repository, run every quickstart.md scenario against a local MongoDB, the collector and Alpaca paper credentials, and record the results in `specs/001-epic-symbol-mapping/validation.md` (SC-004): include the full run's duration (`finished_at − started_at` from `GET /api/v1/runs/{run_id}`), which must be under 30 min (SC-005), and the lookup latency from `scripts/measure_lookups.py` (T101a, SC-001)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; blocks every story.
- **US1 (Phase 3)** and **US2 (Phase 4)**: depend only on Foundational; can run in parallel.
- **US3 (Phase 5)**: needs US1 (mapping model and repository) and US2 (credential provider).
- **US4 (Phase 6)**: needs US3 (`StartRun`, `latest_succeeded`).
- **US5 (Phase 7)**: depends only on Foundational; can run any time after Phase 2.
- **Polish (Phase 8)**: after the stories you intend to ship.

```text
Setup → Foundational ─┬─ US1 ─┐
                      ├─ US2 ─┴─ US3 ── US4 ─┐
                      └─ US5 ────────────────┴─ Polish
```

### Within Each Story

Tests first (they must fail) → domain models → repositories/adapters → use cases → API schemas →
routes → wiring in `main.py`.

### Parallel Opportunities

- Setup: T004–T008.
- Foundational: tests T009–T012; implementation T013–T015 and T017–T018; harness T023–T025.
- US1 ∥ US2 ∥ US5 once Phase 2 is done.
- US3: tests T044–T058 are all [P]; domain modules T059–T063 are [P]; T068 ∥ T069/T070 inputs.
- US4: tests T081–T086; domain T087 ∥ T088.

---

## Parallel Example: User Story 3

```bash
# All US3 tests together (each in its own file):
Task: "Unit tests for normalization and aliasing in tests/unit/domain/matching/test_normalize.py"
Task: "Unit tests for the checks in tests/unit/domain/matching/test_checks.py"
Task: "Contract tests for CollectorGateway in tests/contract/test_collector_gateway.py"
Task: "Contract tests for AlpacaGateway in tests/contract/test_alpaca_gateway.py"
Task: "Integration tests for the run repository in tests/integration/test_run_repo.py"

# Independent domain modules together:
Task: "Implement normalization and aliasing in src/alpaca_gatherer/domain/matching/normalize.py"
Task: "Implement universe filtering in src/alpaca_gatherer/domain/matching/universe.py"
Task: "Implement the window in src/alpaca_gatherer/domain/matching/window.py"
```

---

## Implementation Strategy

### MVP First

1. Phases 1–2 (Setup, Foundational).
2. Phase 3 (US1): lookups over a seeded mapping. **Stop and validate** with quickstart 11–13.
3. Phase 4 (US2) alongside or right after, so that runs become possible.

### Incremental Delivery

1. Foundation → US1 + US2 (P1).
2. US3: mappings are produced by the service itself. Validate the golden test (SC-006).
3. US4: automatic runs.
4. US5: threshold transparency (small; can be pulled earlier).
5. Polish: documentation, drift and leak tests, coverage gate, end-to-end quickstart run without
   the prototype.

---

## Notes

- [P] = different files and no dependency on an incomplete task.
- Each story phase ends at a checkpoint tied to quickstart.md scenarios.
- Commit after each task or logical group.
- T080 is the only task that talks to the live services during development; the recorded fixtures
  are committed so the golden test runs offline.
