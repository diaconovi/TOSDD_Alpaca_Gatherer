# Problem Types (RFC 7807)

Every error response has `Content-Type: application/problem+json` and the fields `type`, `title`,
`status` and `detail` (`instance` is the request path). `type` is
`urn:alpaca-gatherer:problem:<code>`. Responses never contain credentials, stack traces or exception
text.

| Code | Status | Raised by | Extension fields |
|---|---|---|---|
| `validation_error` | 422 | any request body or query that fails validation, including mixed schedule formats, both or neither lookup parameter, past one-time date, unknown timezone | `errors: [{loc, msg}]` |
| `run_in_progress` | 409 | `POST /runs` while a run is running | `active_run_id` |
| `credentials_missing` | 409 | `POST /runs` before credentials are registered | — |
| `credentials_exist` | 409 | `POST /credentials` when already registered | — |
| `credentials_not_found` | 404 | `PATCH /credentials` before registering | — |
| `run_not_found` | 404 | `GET /runs/{run_id}` for an unknown or pruned id | — |
| `instrument_not_found` | 404 | `GET /mappings` for an identifier not in the mapping (by symbol: not a matched symbol) | — |
| `mapping_not_available` | 404 | `GET /mappings` before any run has succeeded | — |
| `internal_error` | 500 | anything unexpected | — |

Run failures are not HTTP errors: they are recorded on the run document as `error.code` (see
[data-model.md](../data-model.md#2-matching-run-m_runs)).
