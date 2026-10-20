# Data Model: Alpaca Gatherer

All collections live in database `MONGO_MAPPING_DB`. Let `M` = `MONGO_MAPPING_COLLECTION`.
All datetimes are stored as UTC BSON dates and converted to a display timezone only when a response
is built.

| Collection | Name | Cardinality |
|---|---|---|
| Instrument mapping (live) | `M` | one document per Capital.com epic |
| Instrument mapping (staging) | `M_staging_<run_id>` | exists only during a run |
| Matching runs | `M_runs` | one document per run; at least `RUN_HISTORY_LIMIT` kept |
| Schedule | `M_schedule` | at most one document (`_id: "schedule"`) |
| Alpaca credentials | `M_credentials` | at most one document (`_id: "alpaca"`) |

## 1. Instrument Mapping (`M`)

| Field | Type | Notes |
|---|---|---|
| `capital_epic` | string | Capital.com epic, case preserved. **Unique index.** |
| `capital_symbol` | string \| null | Capital.com's `symbol` field, when given |
| `capital_name` | string \| null | Instrument name from Capital.com |
| `source` | `catalog` \| `sweep` | How the epic was discovered |
| `status` | `matched` \| `ambiguous` \| `unmatched` | |
| `match_type` | `exact` \| `alias` \| null | Set only when `status = matched` (`alias` covers identifier aliases and name matches) |
| `alpaca_symbol` | string \| null | Set only when `status = matched`. **Unique partial index** where `status = "matched"` |
| `candidates` | list[Candidate] | All candidates examined; for `ambiguous` records these are the ones that passed. No uniqueness constraint |
| `price_diff_pct` | float \| null | Of the chosen (matched) or furthest-progressing candidate |
| `direction_agreement` | float \| null | From the deciding horizon |
| `return_correlation` | float \| null | From the deciding horizon |
| `horizon` | `hourly` \| `session` \| null | Horizon that decided the behavior check |
| `reason` | Reason \| null | Required for `ambiguous` and `unmatched` |
| `run_id` | string | Run that produced this record |
| `updated_at` | datetime | Equal to the producing run's `finished_at` |

**Candidate** (embedded): `alpaca_symbol`, `kind` (`exact` \| `alias` \| `name`), `tradable` (bool),
`active` (bool), `aligned_bars` (int \| null), `price_diff_pct`, `direction_agreement`,
`return_correlation`, `horizon`, `passed` (bool), `failed_check`
(`data` \| `price` \| `behavior` \| `tradability` \| null).

**Reason** (embedded): `code` and `detail` (human-readable string).

| `status` | allowed `reason.code` |
|---|---|
| `ambiguous` | `multiple_candidates`, `name_only_with_unchecked_identifier`, `symbol_conflict` |
| `unmatched` | `not_listed_on_alpaca`, `not_tradable`, `insufficient_data`, `failed_price_check`, `failed_behavior_check` |

**Validation rules**

- `status = matched` ⇒ `alpaca_symbol` and `match_type` are set, `reason` is null.
- `status ≠ matched` ⇒ `alpaca_symbol` and `match_type` are null and `reason` is set.
- `status = ambiguous` ⇒ at least two passing candidates, or `reason.code` explains why there is
  fewer (`name_only_with_unchecked_identifier`, `symbol_conflict`).
- A matched `alpaca_symbol` appears on at most one document (enforced by the index; the conflict pass
  in the matching domain guarantees it before insert — research R15).

**Lookup rules** (FR-021–FR-023, FR-022a)

- By `capital_epic`: exact match on `capital_epic`; any status is returned.
- By `alpaca_symbol`: `{alpaca_symbol: s, status: "matched"}` only. A symbol that is only an ambiguous
  candidate is not found.
- If no run has ever succeeded (live collection absent or empty), a lookup returns the
  `mapping_not_available` problem rather than `instrument_not_found`.

## 2. Matching Run (`M_runs`)

| Field | Type | Notes |
|---|---|---|
| `_id` / `run_id` | string (UUID4) | |
| `trigger` | `manual` \| `scheduled` | |
| `status` | `running` \| `succeeded` \| `failed` | **Unique partial index** on `status` where `status = "running"` (single-run lock, research R6) |
| `started_at` | datetime | Index `started_at: -1` |
| `finished_at` | datetime \| null | Null while running |
| `price_window_end` | datetime | Equal to `started_at` (FR-008) |
| `window` | object \| null | `start`, `end`, `sessions` actually used |
| `thresholds` | object | Snapshot of the threshold set used |
| `counts` | object \| null | `matched`, `ambiguous`, `unmatched`, `total`, plus `by_reason` map |
| `error` | object \| null | `code` and `detail`; set when `status = failed` |

**Error codes**: `collector_unavailable`, `collector_incomplete_data`, `alpaca_unavailable`,
`alpaca_auth_failed`, `credentials_missing`, `credentials_undecryptable`, `skipped_concurrent_run`,
`interrupted_by_restart`, `internal_error`.

**State transitions**

```text
          start (insert, lock acquired)
  (none) ───────────────────────────────▶ running
                                           │  ├─ all stages ok + swap ok ──▶ succeeded
                                           │  ├─ any stage fails ──────────▶ failed (error.code)
                                           │  └─ found at startup ─────────▶ failed (interrupted_by_restart)
  (none) ── scheduled trigger while another run is running ──▶ failed (skipped_concurrent_run)
```

`succeeded` and `failed` are terminal.

**Retention**: after a run reaches a terminal state, executed terminal runs (every terminal run
except `error.code = "skipped_concurrent_run"`) beyond the newest `RUN_HISTORY_LIMIT` are deleted,
oldest first. Skip records are kept separately: at most the newest 20. A `running` run is never
deleted.

**Derived values**: the "last completed run" shown in the schedule view is the newest run with
`status = succeeded`, using its `finished_at`.

## 3. Schedule (`M_schedule`, `_id: "schedule"`)

| Field | Type | Notes |
|---|---|---|
| `kind` | `cron` \| `recurring` \| `one_time` | |
| `cron` | string \| null | When `kind = cron` |
| `day` | string \| null | When `kind = recurring`; normalized lowercase, e.g. `mon-fri` |
| `time` | string \| null | When `kind = recurring`; `HH:MM` |
| `date` | datetime \| null | When `kind = one_time`; stored as UTC |
| `timezone` | string | IANA name; `UTC` when the request omitted it |
| `updated_at` | datetime | |

No document ⇒ no schedule. `PUT` with `schedule: null` deletes the document. A one-time schedule
deletes its own document after it fires or is found missed at startup.

**Validation**: exactly one format per request; see research R7 for field rules. Invalid input never
changes the stored document.

## 4. Alpaca Credentials (`M_credentials`, `_id: "alpaca"`)

| Field | Type | Notes |
|---|---|---|
| `api_key_enc` | string | Fernet token |
| `api_secret_enc` | string | Fernet token |
| `created_at` | datetime | |
| `updated_at` | datetime | |

Plain values exist only in memory, inside a running run. Register = insert (a duplicate `_id` → 409).
Update = `update_one` with `matched_count = 0` → 404.

## 5. Threshold Set (in memory, from `THRESHOLDS_FILE`)

Loaded once at startup and immutable; groups `candidates`, `window`, `price`, `behavior` as listed in
research R9. A snapshot is stored on each run document.

## 6. Settings (in memory, from `.env`)

| Variable | Required | Default | Validation |
|---|---|---|---|
| `COLLECTOR_URL` | yes | — | `http`/`https` URL with host and port |
| `MONGO_URL` | yes | — | `mongodb://` URL without port |
| `MONGO_PORT` | no | 27017 | 1–65535 |
| `MONGO_MAPPING_DB` | yes | — | non-empty |
| `MONGO_MAPPING_COLLECTION` | yes | — | non-empty, no `$` and no `.` |
| `LOGGING` | no | `INFO` | `INFO` \| `DEBUG` \| `WARNING` |
| `TIME_ZONE` | no | `UTC` | valid IANA zone |
| `FIELD_ENCRYPTION_KEY` | yes | — | valid Fernet key |
| `THRESHOLDS_FILE` | no | `config/thresholds.yaml` | file exists and validates |
| `RUN_HISTORY_LIMIT` | no | 50 | ≥ 50 (FR-012a minimum) |
| `ALPACA_TRADING_URL` | no | `https://paper-api.alpaca.markets` | URL |
| `ALPACA_DATA_URL` | no | `https://data.alpaca.markets` | URL |

Any failure stops startup with a message naming the variable.
