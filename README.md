# Alpaca Gatherer

Keeps an up-to-date mapping between Capital.com instruments (**epics**) and Alpaca Markets
instruments (**symbols**), so other services can translate an instrument from one broker to the
other with a single lookup. The matching process is documented in
[docs/matching-process.md](docs/matching-process.md).

## Requirements

- [uv](https://docs.astral.sh/uv/); Python 3.14 is fetched by uv (`uv python install 3.14`).
- A local MongoDB, e.g. `mongod --dbpath ~/data/db` started from a terminal.
- The collector service, reachable at `COLLECTOR_URL`.
- SSH access to the repository hosting `to_collector_client` (a git dependency).
- An Alpaca API key and secret (paper keys are fine).

## Setup and start

```bash
uv sync
cp .env.example .env
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# put the key into FIELD_ENCRYPTION_KEY and set MONGO_MAPPING_DB / MONGO_MAPPING_COLLECTION in .env
uv run uvicorn alpaca_gatherer.main:app --host 127.0.0.1 --port 8002
```

Every setting is validated at startup; a missing or invalid value (or thresholds file) stops the
process with a message naming it. Thresholds live in `config/thresholds.yaml`.

Interactive API docs: <http://127.0.0.1:8002/docs>.

## API (`/api/v1`)

| Method and path | Purpose |
|---|---|
| `POST /credentials`, `PATCH /credentials` | Register (201) or replace (204) the Alpaca key and secret; stored Fernet-encrypted, never returned |
| `POST /runs` | Start a full matching run in the background (202 + `Location`) |
| `GET /runs`, `GET /runs/{run_id}` | Run history, newest first (50 executed runs + 20 skipped kept) |
| `GET /schedules/current`, `PUT /schedules/current` | View or set the schedule: `{"cron": "*/5 * * * *"}`, `{"schedule": {"day": "mon-fri", "time": "18:00"}, "timezone": "America/New_York"}`, `{"schedule": {"date": "2026-12-01T19:48:19Z"}}`, or `{"schedule": null}` |
| `GET /mappings?capital_epic=…` or `?alpaca_symbol=…` | Look up a mapping (exactly one parameter) |
| `GET /thresholds` | The thresholds in use |

Errors are RFC 7807 problem documents (`application/problem+json`); see
`specs/001-epic-symbol-mapping/contracts/`.

Quick start once the service runs:

```bash
API=http://127.0.0.1:8002/api/v1
curl -X POST $API/credentials -H 'content-type: application/json' \
     -d '{"api_key":"<key>","api_secret":"<secret>"}'
curl -X POST $API/runs                       # ~20 minutes for the full universe
curl "$API/mappings?capital_epic=BRKB"
```

## Trust model

- **No authentication** in this version (FR-027): bind to loopback (the default above) or an
  internal network only. Credentials are write-only, so a caller can replace them but never read
  them.
- **Single instance**: the run lock lives in MongoDB, so several instances never run two matching
  runs at once, but a schedule change made on one instance reaches the others only after their
  restart.

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
MONGO_TEST_URL=mongodb://localhost:27017 uv run pytest     # unit, integration, contract, golden
uv run pytest tests/unit --cov                              # coverage gate: ≥ 80 % on domain + application
```

Integration tests use a disposable database (a unique name per session, dropped afterwards) on the
MongoDB given by `MONGO_TEST_URL`; without it the session fails, unless you pass `--allow-no-mongo`
to skip only those tests (not allowed for merge).

The coverage gate is configured in `pyproject.toml` (`[tool.coverage]`, `fail_under = 80`, measured
on `alpaca_gatherer.domain` and `alpaca_gatherer.application` by the unit tests).

Tooling scripts (not part of the service):

- `python -m scripts.record_reference_window` and `scripts/convert_baseline.py` build the golden-test
  fixture in `tests/fixtures/reference_window/` (see its README).
- `scripts/measure_lookups.py` measures lookup latency against a running service (SC-001).
