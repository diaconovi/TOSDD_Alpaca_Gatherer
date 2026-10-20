# Phase 0 Research: Alpaca Gatherer

All Technical Context unknowns are resolved below. Each entry records the decision, why it was
chosen, and the alternatives considered. Inputs: the feature spec and clarifications, the
constitution (v1.0.0), the user's technical brief, the public API of `to_collector_client` 0.2.1,
and the prototype's documentation (read as reference only; nothing from it is used at runtime).

## R1. Python version

- **Decision**: Python 3.14 (`requires-python = ">=3.14"`, `.python-version` = `3.14`), managed by uv.
- **Rationale**: Constitution Principle II fixes the runtime at 3.14. The brief's "3.12+" is a lower
  bound that 3.14 satisfies, so there is no conflict in practice.
- **Alternatives**: `>=3.12` as written in the brief — rejected because it would let the project be
  tested on interpreters the constitution does not allow.

## R2. Collector access

- **Decision**: Use the `to_collector_client` package (`CollectorClient`) for every call to the
  collector, wrapped by an infrastructure adapter `CollectorGateway` that implements the
  application port `CapitalCatalogPort`. The client is synchronous, so each call runs through
  `asyncio.to_thread`, bounded by an `asyncio.Semaphore` (default 4). `COLLECTOR_URL` is parsed into
  `scheme`, `host` and `port` for the client constructor. The dependency is declared as the same git
  source the platform already uses
  (`ssh://git@github.com/diaconovi/Trade_Ops_Library.git`, subdirectory `packages/to_collector`).
- **Rationale**: Constitution Principle VII requires communicating with other services only through
  their client package; the brief's "httpx for the collector" is satisfied because the client is
  built on httpx. The client documents that it is thread-safe and raises only its own exception
  hierarchy (`CollectorConnectionError`, `CollectorServerError`, …), which maps cleanly onto run
  failure causes.
- **Alternatives**: a hand-written httpx client — rejected (violates Principle VII and duplicates
  the collector's contract).
- **Calls used**: `discover_market_catalogs`, `get_shares_market(region, catalog, max_doc=500)` for
  the four US catalogs, `search_markets(epics=…)` in batches of 50 for the epic sweep (a 400 on a
  batch is bisected), and `get_prices(epic, resolution=HOUR, from_, to)` for hourly bars (404 means
  "no history", not retried).

## R3. Alpaca access

- **Decision**: An async httpx adapter (`AlpacaGateway`, implementing `AlpacaMarketPort`) calling the
  Alpaca REST APIs directly: `GET /v2/assets?asset_class=us_equity` and `GET /v2/calendar` on the
  trading API, and `GET /v2/stocks/bars` (timeframe `1Hour`, `adjustment=raw`, `feed=sip`, 100 symbols
  per request, following `next_page_token`) on the data API. Responses are parsed into pydantic
  models. Two optional settings with defaults are added: `ALPACA_TRADING_URL`
  (default `https://paper-api.alpaca.markets`) and `ALPACA_DATA_URL`
  (default `https://data.alpaca.markets`).
- **Rationale**: The service is async end to end; `alpaca-py` is synchronous and its models are
  loosely typed for strict mypy. Three endpoints are a small, stable surface, easy to cover with
  contract tests.
- **Alternatives**: `alpaca-py` in worker threads — workable but adds a large dependency and thread
  hops for every bar page.

## R4. MongoDB driver and connection

- **Decision**: PyMongo's native async API (`pymongo.AsyncMongoClient`, PyMongo ≥ 4.13). The
  connection string is built from `MONGO_URL` and `MONGO_PORT`. All collections live in
  `MONGO_MAPPING_DB`; the live mapping collection is `MONGO_MAPPING_COLLECTION`, and the others are
  named from it (`<name>_runs`, `<name>_schedule`, `<name>_credentials`).
- **Rationale**: Motor is deprecated in favor of PyMongo's async API, which ships its own type hints.
- **Alternatives**: Motor — deprecated. mongomock — does not support the async API.

## R5. Atomic mapping replacement

- **Decision**: A run writes all records into a staging collection `<mapping>_staging_<run_id>`,
  builds the same indexes there, then calls `renameCollection` to the live name with
  `dropTarget=True`. On failure the staging collection is dropped. At startup every leftover
  `<mapping>_staging_*` collection is dropped.
- **Rationale**: Renaming within one database is atomic for readers: a lookup sees either the whole
  old snapshot or the whole new one (FR-010, FR-011, SC-008). It needs no replica set or transactions,
  which suits a local standalone MongoDB.
- **Alternatives**: a multi-document transaction (requires a replica set); a `snapshot_id` field with
  a pointer flip (doubles storage and needs cleanup).

## R6. One run at a time

- **Decision**: The authoritative lock lives in MongoDB: a **unique partial index** on the runs
  collection, on `status` with `partialFilterExpression: {status: "running"}`. Starting a run inserts a
  `running` document; a `DuplicateKeyError` means another run is active. An in-process `asyncio.Lock`
  sits in front of it to avoid needless round trips (as the brief requests). A manual request then
  gets 409 with the active `run_id`. A **scheduled** trigger that collides is recorded as a run
  document with `trigger: scheduled`, `status: failed`, `error.code: "skipped_concurrent_run"`, and the
  active run's id in the detail, then logged.
- **Rationale**: The unique index keeps the guarantee correct across processes and restarts, which a
  process-local lock alone cannot (Principle VI). Recording skips as `failed` with a reason code keeps
  the run states to the three the spec defines (FR-012a) while still leaving an audit trail.
- **Alternatives**: a separate `skipped` status — rejected to keep the state set fixed; skip without
  recording — rejected because operators could not see why a scheduled run did not happen.

## R7. Scheduling

- **Decision**: APScheduler 3.11 `AsyncIOScheduler`, in-memory job store, a single job id
  `matching-run`. The persisted schedule document is the source of truth; on startup and on every
  schedule change the job is rebuilt from it. Triggers:
  - cron → `CronTrigger.from_crontab(expr, timezone=ZoneInfo(tz))` (5-field standard cron);
  - recurring → `CronTrigger(day_of_week=day, hour=h, minute=m, timezone=…)`;
  - one-time → `DateTrigger(run_date=…, timezone=…)`.
  Job options `coalesce=True`, `max_instances=1`, `misfire_grace_time=60` seconds, so runs missed
  while the service was down are not executed retroactively. At startup a one-time schedule whose
  instant has passed is cleared and logged as missed (FR-020). The next run time comes from
  `trigger.get_next_fire_time(None, now)`, which handles DST transitions using `zoneinfo`.
- **Validation** (before any trigger is built; all failures are 422 naming the field):
  exactly one of `cron` or `schedule` must be present, or `schedule: null`; inside `schedule`, exactly one of `date` or
  `day`+`time`; `day` must be a weekday token (`mon`…`sun`), an ascending range (`mon-fri`) or a comma
  list of those; `time` must match `HH:MM` 00:00–23:59; `date` must be timezone-aware ISO 8601 and in
  the future; `timezone` must resolve with `zoneinfo.ZoneInfo`; cron must parse with `from_crontab`.
  A one-time `date` given with an offset keeps its instant; `timezone` controls only how it is shown.
- **HTTP method**: `PUT /api/v1/schedules/current` replaces the single schedule resource (idempotent), in line
  with Principle IV; the brief's POST is mapped to PUT.
- **Rationale**: APScheduler handles cron and timezone arithmetic correctly. Keeping the jobs derived
  from MongoDB satisfies the restart requirement (FR-019) and keeps the process itself stateless
  (Principle VI): the job is a cache of persisted state.
- **Known limit**: this version targets a single instance. With several instances each would fire the
  job; the R6 lock still guarantees only one run, and the others record a skip. A schedule changed on
  one instance is picked up by the others only on restart — documented in the README.
- **Alternatives**: APScheduler's MongoDB job store — it pickles job state and still needs our own
  schedule document for display; APScheduler 4 — still pre-release.

## R8. Credential encryption

- **Decision**: `cryptography.fernet.Fernet(FIELD_ENCRYPTION_KEY)`. The key is validated at startup by
  constructing `Fernet` (fail fast if missing or malformed). Key and secret are encrypted separately
  and stored as ciphertext strings. Decryption happens only inside a run; `InvalidToken` makes the run
  fail with code `credentials_undecryptable` ("update the credentials"). `PATCH` overwrites the
  ciphertext without decrypting the old value, so it works after a key change.
- **Rationale**: Fernet gives authenticated encryption with a standard key format (SC-003).
- **Alternatives**: MongoDB client-side field-level encryption — needs a key vault and
  enterprise/Atlas features; overkill here.

## R9. Threshold configuration file

- **Decision**: YAML at `THRESHOLDS_FILE` (default `config/thresholds.yaml`), parsed with PyYAML
  `safe_load` into a frozen pydantic model with four groups and range validation:

  | Group | Field | Default | Rule |
  |---|---|---|---|
  | `candidates` | `name_ratio` | 0.90 | 0 < x ≤ 1 |
  | `candidates` | `max_name_candidates` | 3 | ≥ 1 |
  | `window` | `sessions` | 20 | ≥ 2 |
  | `window` | `embargo_minutes` | 20 | ≥ 0 |
  | `window` | `min_bars` | 60 | ≥ 2 |
  | `window` | `feed` | `sip` | `sip` or `iex` |
  | `price` | `price_tol_pct` | 1.0 | > 0 |
  | `price` | `spread_mult` | 0.5 | ≥ 0 |
  | `behavior` | `corr_threshold` | 0.70 | −1 ≤ x ≤ 1 |
  | `behavior` | `dir_threshold` | 0.75 | 0 ≤ x ≤ 1 |
  | `behavior` | `min_sig_moves` | 10 | ≥ 1 |
  | `behavior` | `min_session_returns` | 12 | ≥ 1 |

  Unknown keys are rejected (`extra="forbid"`). `GET /api/v1/thresholds` returns this structure.
- **Rationale**: The grouping follows the matching stages (FR-007); the defaults are the values the
  prototype's reference run validated.
- **Alternatives**: TOML (also fine, but the brief names `thresholds.yaml`); environment variables
  (flat, which loses the grouping).

## R10. Errors

- **Decision**: One problem-details module in the interface layer. It registers handlers for
  `RequestValidationError` (422, with an `errors` extension listing `loc`/`msg`), for the service's
  `DomainError` subclasses (each maps to a fixed status and a `type` URI
  `urn:alpaca-gatherer:problem:<code>`), and a fallback 500 that never includes exception text.
  The media type is `application/problem+json`.
- **Rationale**: Principle V; one mapping table keeps status codes consistent.

## R11. Logging

- **Decision**: Standard `logging`, level from `LOGGING`. A custom `Formatter.formatTime` renders
  timestamps in `ZoneInfo(TIME_ZONE)`. A `contextvars.ContextVar[str | None]` holds the current
  `run_id`, and a `logging.Filter` injects it into every record (`run_id=-` outside runs). A redaction
  filter masks any value registered as secret. Credentials are never passed to log calls.
- **Rationale**: Meets the brief's logging rules and FR-025/SC-003 without a third-party logging
  stack.

## R12. Testing strategy

- **Decision**:
  - **Unit** (`tests/unit/<layer>`): domain matching functions, schedule parsing and validation,
    next-run rendering including DST, Fernet round trip, run-history pruning policy, startup recovery
    use case, lookup rules — all against in-memory fakes of the ports. No I/O.
  - **Integration** (`tests/integration`): MongoDB repositories, staging swap, the unique running-run
    index, and every HTTP endpoint through `httpx.AsyncClient(transport=ASGITransport(app))`, against a
    **disposable local MongoDB** (a uniquely named database per test session, dropped afterwards).
    Tests are skipped with a clear message if `MONGO_TEST_URL` is not reachable.
  - **Contract** (`tests/contract`): the Alpaca and collector adapters against recorded responses,
    using `respx` to intercept httpx (which also covers the collector client's internal httpx client).
  - **Golden** (`tests/golden`): the matching domain run over a committed fixture set
    (`tests/fixtures/reference_window/`) checked against expected classifications (SC-006).
  - **Guard**: a test asserting that no source file imports from, or refers to, the prototype folder
    (FR-005).
  - Coverage: `pytest-cov`, gate `--cov-fail-under=80` on `domain` and `application` (Principle IX).
- **Rationale**: Principle IX requires real integration tests for repositories and HTTP clients;
  mongomock cannot run the async driver, so the brief's "disposable local MongoDB" option is used.
- **Alternatives**: `mongomock-motor` — tied to Motor and does not reproduce index or rename
  semantics, which are exactly what the tests must prove.

## R13. Comparison window

- **Decision**: The window ends at the run's `started_at` (stored as `price_window_end`, FR-008). The
  last `window.sessions` complete sessions are taken from the Alpaca calendar, each ending at least
  `window.embargo_minutes` before `price_window_end`. Both brokers are queried with the same
  `[floor(first open), last close]` UTC range, with 1-hour bars, regular session only.
- **Rationale**: This is the prototype's validated method, with the window end fixed to the run start
  as clarified.

## R14. Retries and rate limits

- **Decision**: `tenacity` exponential backoff with jitter, 5 attempts, on connection errors, HTTP
  5xx and 429 for both gateways. Collector price calls are capped at 4 concurrent requests (the
  collector also rate-limits globally). No on-disk cache.
- **Rationale**: Statelessness (Principle VI) rules out the prototype's local file cache. Without it
  a full run is expected to take about 20 minutes, inside SC-005's 30-minute budget.
- **Risk**: run time depends on collector throughput; a run's duration is recorded so it can be
  watched.

## R15. One symbol per match

- **Decision**: After classification, a conflict pass checks matched symbols. If several epics are
  matched to the same symbol, all of them are reclassified `ambiguous` with reason `symbol_conflict`
  and the competing epics listed. This backs the unique partial index on `alpaca_symbol` for matched
  records.
- **Rationale**: The brief's index requires a one-to-one mapping; the prototype's reference run had
  no such conflicts, so this is a rare safety case. The spec edge case was updated to match.

## R16. API resources (Principle IV)

- **Decision**: Plural, resource-oriented paths, as chosen by the user:

  | Brief | Planned |
  |---|---|
  | `GET /instrument` | `GET /api/v1/thresholds` |
  | `POST /instrument` | `POST /api/v1/runs` |
  | `GET /instrument/runs`, `/{run_id}` | `GET /api/v1/runs`, `GET /api/v1/runs/{run_id}` |
  | `GET/POST /instrument/schedule` | `GET /api/v1/schedules/current`, `PUT /api/v1/schedules/current` |
  | `GET /match?…` | `GET /api/v1/mappings?capital_epic=…` or `?alpaca_symbol=…` |
  | `POST/PATCH /account` | `POST/PATCH /api/v1/credentials` |

  `POST /api/v1/credentials` returns **201 with an empty body** (the brief's status; FR-024's "no
  content" is met because there is no body). `PATCH` returns 204.

## R17. Packaging and startup

- **Decision**: Package `alpaca_gatherer` under `src/` (uv `src` layout, hatchling build backend).
  Start with `uv run uvicorn alpaca_gatherer.main:app --host 127.0.0.1 --port 8002`. Tooling: Ruff
  (lint + format), mypy `--strict` (configured in `pyproject.toml`), pytest, pytest-asyncio,
  pytest-cov, respx.
- **Rationale**: Principle II (uv only, `uv run`) and FR-029 (run from a terminal, no containers);
  loopback by default per the access-control decision (FR-027).
