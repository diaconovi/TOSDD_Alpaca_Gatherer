# Quickstart & Validation Guide: Alpaca Gatherer

Proves the feature end to end on a developer machine. API details are in
[contracts/openapi.yaml](contracts/openapi.yaml) and [contracts/problems.md](contracts/problems.md);
stored shapes are in [data-model.md](data-model.md).

## Prerequisites

- uv installed; Python 3.14 is fetched by uv (`uv python install 3.14` if needed).
- A local MongoDB on `localhost:27017` (for example `mongod --dbpath ~/data/db`, run from a terminal).
- The collector service reachable at `COLLECTOR_URL` (default `http://localhost:8001`).
- SSH access to the repository that hosts `to_collector_client`.
- An Alpaca API key and secret (paper keys are fine).
- The `alpacaMatcher/` prototype folder is **not** needed; remove or rename it to prove FR-005.

## Setup

```bash
uv sync                                    # creates .venv from uv.lock
cp .env.example .env
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# paste the key into FIELD_ENCRYPTION_KEY, set MONGO_MAPPING_DB / MONGO_MAPPING_COLLECTION
uv run uvicorn alpaca_gatherer.main:app --host 127.0.0.1 --port 8002
```

The service binds to loopback by default. It has no authentication (FR-027): expose it only on a
trusted internal network.

Interactive docs: `http://127.0.0.1:8002/docs`. Below, `API=http://127.0.0.1:8002/api/v1`.

## Validation scenarios

| # | Action | Expected |
|---|---|---|
| 1 | Start with `FIELD_ENCRYPTION_KEY` empty, then with a bad `TIME_ZONE`, then with `THRESHOLDS_FILE` pointing at a missing file | Each time the process exits before serving, naming the variable or file |
| 2 | `curl $API/thresholds` | 200; groups `candidates`, `window`, `price`, `behavior` equal to `config/thresholds.yaml` |
| 3 | `curl -X POST $API/runs` (no credentials yet) | 409 `credentials_missing` |
| 4 | `curl -X POST $API/credentials -H 'content-type: application/json' -d '{"api_key":"…","api_secret":"…"}'` | 201, empty body |
| 5 | Repeat step 4 | 409 `credentials_exist` |
| 6 | `mongosh <db> --eval 'db.<M>_credentials.findOne()'` | Only Fernet tokens; the plain key and secret do not appear (SC-003). `grep` the service log for them: no hits |
| 7 | `curl -X PATCH $API/credentials …` | 204 |
| 8 | `curl -X POST $API/runs` | 202 `{run_id, status: "running", started_at}` within 1 s (SC-005) |
| 9 | Repeat step 8 immediately | 409 `run_in_progress` with `active_run_id` |
| 10 | `curl $API/runs/<run_id>` until `status` is `succeeded` | `counts` filled; `price_window_end` equals `started_at` |
| 11 | `curl "$API/mappings?capital_epic=BRKB"` and `curl "$API/mappings?alpaca_symbol=BRK.B"` | 200 for both, pointing at each other (SC-001) |
| 12 | `curl "$API/mappings?capital_epic=X&alpaca_symbol=Y"` and `curl "$API/mappings"` | 422 `validation_error` |
| 13 | Look up an unmatched epic, an ambiguous epic, and an unknown epic | 200 `unmatched` with reason; 200 `ambiguous` with `alpaca_symbol: null` and candidates; 404 `instrument_not_found` |
| 14 | `curl -X PUT $API/schedules/current -d '{"schedule":{"day":"mon-fri","time":"18:00"},"timezone":"America/New_York"}'` | 200; `next_run` is the next weekday 18:00 with offset `-04:00`/`-05:00` (SC-002) |
| 15 | `PUT` `{"cron":"*/5 * * * *"}` with no timezone | `timezone: "UTC"`, `next_run` ≤ 5 min ahead |
| 16 | `PUT` with mixed formats, `{"cron":"61 * * * *"}`, `day: "mon-xyz"`, `time: "25:00"`, a past `date`, `timezone: "Mars/Base"` | 422 each; `GET /schedules/current` unchanged |
| 17 | Stop the service while a schedule is active, start it again, `GET /schedules/current` | Same schedule, timezone and `last_run`; `next_run` recomputed (SC-007) |
| 18 | Start a run, kill the process with Ctrl+C mid-run, restart, `GET /runs/<run_id>` | `failed`, `error.code = interrupted_by_restart`; lookups still return the previous mapping (FR-012b) |
| 19 | Stop the collector, start a run | Run ends `failed` with `collector_unavailable`; lookups unchanged (SC-008) |
| 20 | `PUT {"schedule": null}` | 200 with `schedule: null`, `next_run: null`, `timezone: "UTC"` |

## Automated checks

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
MONGO_TEST_URL=mongodb://localhost:27017 uv run pytest          # unit + integration + contract + golden
# Without a local MongoDB (not allowed for merge): uv run pytest --allow-no-mongo
uv run pytest tests/unit --cov=alpaca_gatherer.domain --cov=alpaca_gatherer.application --cov-fail-under=80
```

All of these must pass before merge (constitution, "Development Workflow & Quality Gates").
