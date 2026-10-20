# Validation: quickstart scenarios against live services (T104)

**Date**: 2026-10-18 (UTC) · **Result**: 20 / 20 scenarios pass.

## Setup

| Item | Value |
|---|---|
| Prototype folder | moved out of the repository (to `../alpacaMatcher_prototype`) before the run: SC-004 |
| Service | `uv run uvicorn alpaca_gatherer.main:app --host 127.0.0.1 --port 8002`, `TIME_ZONE=America/Mexico_City`, default `config/thresholds.yaml` |
| MongoDB | local standalone on `localhost:27017`, dedicated database `alpaca_gatherer_validation` (dropped afterwards) |
| Collector | the local collector at `http://localhost:8001` |
| Alpaca | paper credentials, registered through `POST /api/v1/credentials` |

The scenarios were driven by a script that started, stopped (SIGINT, as Ctrl+C) and restarted the
service; the results below are its output.

## Results

| # | Scenario | Result |
|---|---|---|
| 1 | Bad `FIELD_ENCRYPTION_KEY`, `TIME_ZONE`, `THRESHOLDS_FILE` | PASS: each exits 1 before serving: `FIELD_ENCRYPTION_KEY: must be a Fernet key …`, `TIME_ZONE: must be a valid IANA timezone …`, `Thresholds file config/missing.yaml (THRESHOLDS_FILE) does not exist` |
| 2 | `GET /thresholds` | PASS: 200, equal to `config/thresholds.yaml` |
| 3 | `POST /runs` without credentials | PASS: 409 `credentials_missing` |
| 4 | `POST /credentials` | PASS: 201, empty body |
| 5 | Repeat | PASS: 409 `credentials_exist` |
| 6 | Stored document and log | PASS: only `api_key_enc`, `api_secret_enc` (Fernet tokens), `created_at`, `updated_at`; plain values in neither the document nor the service log |
| 7 | `PATCH /credentials` | PASS: 204 |
| 8 | `POST /runs` | PASS: 202 in 4 ms with `Location` |
| 9 | Repeat immediately | PASS: 409 `run_in_progress`, `active_run_id` = the running run |
| 10 | Run to completion | PASS: `succeeded`; 3,587 epics: 3,479 matched, 1 ambiguous, 107 unmatched (`insufficient_data` 76, `failed_behavior_check` 24, `not_tradable` 4, `not_listed_on_alpaca` 2, `failed_price_check` 1); `price_window_end = started_at`; **duration 18.0 min** (SC-005: < 30 min) |
| 11 | `capital_epic=BRKB`, `alpaca_symbol=BRK.B` | PASS: `BRKB` → `BRK.B` (alias) and back |
| 12 | Both / neither parameter | PASS: 422 each |
| 13 | Unmatched, ambiguous, unknown epic | PASS: `AAA` unmatched `insufficient_data` (HTTP 404 history); `WSOB` ambiguous `name_only_with_unchecked_identifier`, no symbol, candidates `WSO`, `WSO.B`; unknown epic 404 `instrument_not_found` |
| 14 | Recurring `mon-fri 18:00 America/New_York` | PASS: `next_run 2026-10-19T18:00:00-04:00` |
| 15 | `cron */5 * * * *`, no timezone | PASS: timezone `UTC`, next run 281 s ahead |
| 16 | Mixed formats, cron `61 * * * *`, `mon-xyz`, `25:00`, past date, `Mars/Base` | PASS: 422 each, naming `schedule`, `cron`, `schedule.day`, `schedule.time`, `schedule.date`, `timezone`; schedule unchanged |
| 17 | Restart with the schedule active | PASS: schedule, timezone and `last_run` identical after restart; `next_run` recomputed |
| 18 | Kill mid-run, restart | PASS: run `failed` / `interrupted_by_restart`; lookups return the previous mapping |
| 19 | Collector unreachable | PASS: run `failed` / `collector_unavailable` (“discover catalogs: the collector could not be reached”); lookups unchanged (SC-008). The shared collector was not stopped: the service was restarted with `COLLECTOR_URL` pointing at a closed port |
| 20 | `PUT {"schedule": null}` | PASS: `schedule: null`, `next_run: null`, `timezone: "UTC"` |

## Success criteria

| Criterion | Evidence |
|---|---|
| SC-001 lookups p95 < 1 s | `scripts/measure_lookups.py`: 200 lookups (100 epics, 100 matched symbols): p50 3.3 ms, **p95 4.9 ms**, max 26.3 ms |
| SC-003 no plain credentials | scenario 6, and the full service log after all scenarios: no occurrence |
| SC-004 works without the prototype | the whole validation ran with the prototype folder outside the repository |
| SC-005 ack < 1 s, full run < 30 min | 4 ms; 18.0 min |
| SC-006 agreement ≥ 99 % | golden test: 3,577 / 3,580 common epics (99.92 %); see `tests/fixtures/reference_window/README.md` |
| SC-007 restart keeps schedule | scenario 17 |
| SC-008 failed run keeps lookups | scenarios 18 and 19 |
