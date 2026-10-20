# Feature Specification: Alpaca Gatherer — Epic ↔ Symbol Mapping Service

**Feature Branch**: `001-epic-symbol-mapping`

**Created**: 2026-10-18

**Status**: Draft

**Input**: User description: "Build \"Alpaca Gatherer\", a backend service that keeps an up-to-date
mapping between Capital.com instruments (epics) and Alpaca Markets instruments (symbols), so other
services in the trading platform can translate an instrument from one broker to the other without
running the matching logic themselves." (full description: capabilities 1–8, edge cases, success
criteria and out-of-scope items as provided in the `/speckit-specify` request)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Translate an instrument between brokers (Priority: P1)

An internal consumer service holds a Capital.com epic (e.g., from a market-data feed) and needs the
equivalent Alpaca symbol to place an order, or holds an Alpaca symbol and needs the Capital.com epic.
It sends a single lookup with exactly one identifier and receives the stored mapping record: the
counterpart identifier, the match status, the quality measures behind the decision and, for
unmatched instruments, the reason.

**Why this priority**: This is the reason the service exists. Without lookups, no other service
benefits from the mapping.

**Independent Test**: Seed the store with a known mapping, then look up a matched epic, a matched
symbol, an unmatched epic, and an unknown identifier; verify each response.

**Acceptance Scenarios**:

1. **Given** epic `BRKB` is stored as matched to symbol `BRK.B`, **When** a consumer looks up epic
   `BRKB`, **Then** the response contains symbol `BRK.B`, its match status and its quality measures.
2. **Given** the same mapping, **When** a consumer looks up symbol `BRK.B`, **Then** the response
   contains epic `BRKB` (a matched symbol belongs to at most one epic).
3. **Given** epic `APPL` is stored as unmatched, **When** it is looked up, **Then** the response
   states it is unmatched and includes the reason category and detail.
4. **Given** any state, **When** a consumer provides both an epic and a symbol, or neither,
   **Then** a validation error explains that exactly one identifier is required.
5. **Given** an identifier that is not in the stored mapping, **When** it is looked up, **Then** a
   not-found error is returned that distinguishes "unknown instrument" from "known but unmatched".

---

### User Story 2 - Register and maintain Alpaca credentials (Priority: P1)

An operator registers the Alpaca API key and secret once, and updates them when they rotate. The
service stores them encrypted and never reveals them.

**Why this priority**: The service cannot read Alpaca instruments or prices, and therefore cannot
match anything, until credentials exist.

**Independent Test**: Register credentials, inspect the data store directly to confirm only
ciphertext is present, update them, and confirm no operation ever returns the plain values.

**Acceptance Scenarios**:

1. **Given** no credentials are registered, **When** the operator registers a key and secret,
   **Then** the request succeeds with no content and the values are stored encrypted.
2. **Given** credentials are registered, **When** the operator registers again, **Then** a
   conflict error is returned and the operator is directed to the update operation.
3. **Given** credentials are registered, **When** the operator updates them, **Then** the request
   succeeds with no content and subsequent runs use the new values.
4. **Given** no credentials are registered, **When** the operator attempts an update, **Then** a
   not-found error directs the operator to register first.
5. **Given** any state, **When** any operation is called, **Then** no response, log line or error
   message contains the plain key or secret.

---

### User Story 3 - Run matching on demand (Priority: P2)

An operator starts a matching run. The service acknowledges immediately; the run gathers the
Capital.com instrument universe from the collector and the Alpaca assets and prices, applies the
matching process with the configured thresholds, and on success refreshes the stored mapping.

**Why this priority**: Produces the data that User Story 1 serves. Needed before the schedule
adds value.

**Independent Test**: With credentials registered and stubbed broker data, trigger a run, confirm
the immediate acknowledgement, wait for completion, and verify the stored mapping and last-run
information.

**Acceptance Scenarios**:

1. **Given** credentials are registered and no run is in progress, **When** the operator triggers
   a run, **Then** the request is accepted immediately with a run identifier and the run continues
   in the background.
2. **Given** a run completes successfully, **When** a consumer looks up an instrument, **Then**
   results reflect the new run, and the last completed run time is updated.
3. **Given** a run is in progress, **When** another run is requested (manually or by the
   schedule), **Then** the new request is rejected with a conflict error (manual) or skipped and
   logged (scheduled); the running run is unaffected.
4. **Given** no credentials are registered, **When** a run is requested, **Then** it is rejected
   with an error stating that Alpaca credentials must be registered first.
5. **Given** the collector is unreachable or returns incomplete data, **When** a run executes,
   **Then** the run is marked failed with the cause, and the previously stored mapping remains
   unchanged and available for lookups.
6. **Given** a run was started and its identifier returned, **When** the operator retrieves that
   run, **Then** its current state (running, succeeded or failed), times, counts and any failure
   cause are returned; **When** the operator lists runs, **Then** recent runs appear newest first.

---

### User Story 4 - Schedule automatic matching runs (Priority: P2)

An operator sets when matching runs should happen automatically, using one of three formats: a cron
expression, a recurring day/time schedule, or a single one-time run, optionally with an IANA
timezone. The operator can view the active schedule, the next run time, the last completed run time
and the timezone, and can disable scheduling by setting the schedule to null.

**Why this priority**: Keeps the mapping current without manual action, but on-demand runs already
deliver the core value.

**Independent Test**: Set each schedule format, read back the schedule and next-run time, restart
the service, and confirm the schedule and last-run information persist and the next run fires.

**Acceptance Scenarios**:

1. **Given** any state, **When** the operator sets `{"cron": "*/5 * * * *"}`, **Then** the response
   confirms the applied schedule and the next run time, at most 5 minutes in the future.
2. **Given** any state, **When** the operator sets `{"schedule": {"day": "mon-fri", "time": "18:00"},
   "timezone": "America/New_York"}`, **Then** the next run is the next weekday at 18:00 New York
   time, shown in that timezone.
3. **Given** any state, **When** the operator sets `{"schedule": {"date": "<future timestamp>"}}`,
   **Then** exactly one run is scheduled at that instant; after it runs, the schedule shows no next
   run.
4. **Given** a schedule is active, **When** the operator sets the schedule to null, **Then** no
   further scheduled runs happen and the view shows no schedule and no next run.
5. **Given** any state, **When** a request mixes formats, or contains an invalid cron expression,
   invalid day range, invalid time, a past one-time date or an unknown timezone, **Then** a
   validation error names the offending field and the existing schedule is unchanged.
6. **Given** a schedule is active and a run has completed, **When** the service restarts, **Then**
   the schedule, its timezone and the last completed run time are unchanged and the next run is
   recomputed from the current time.
7. **Given** no timezone is supplied, **When** a schedule is set, **Then** it is interpreted and
   displayed in UTC.

---

### User Story 5 - Inspect matching thresholds (Priority: P3)

An operator retrieves the threshold values the matching process is currently using, grouped the
way the process applies them (identifier/name candidate selection, data window, price check,
behavior check), to understand or audit why instruments were matched or rejected.

**Why this priority**: Supports transparency and troubleshooting; not needed to produce or
consume mappings.

**Independent Test**: Start the service with a known threshold file and verify the returned values
equal the file's values in the documented structure.

**Acceptance Scenarios**:

1. **Given** a valid threshold file at startup, **When** the operator requests the thresholds,
   **Then** every value from the file is returned, grouped by matching stage.
2. **Given** the threshold file is missing or invalid, **When** the service starts, **Then** it
   refuses to start and reports which file and which field is the problem.

---

### Edge Cases

- **Concurrent runs**: only one run executes at a time; manual requests during a run get a
  conflict error with the identifier of the running run; scheduled triggers during a run are
  skipped, logged, and recorded as a run with state `failed` and reason `skipped_concurrent_run`;
  these records do not count toward the retained-run minimum.
- **No credentials**: runs are rejected with a clear error. Lookups still serve whatever mapping
  is stored; if no run has ever completed, lookups return a "mapping not yet available" error.
- **Credential lifecycle**: registering twice → conflict; updating before registering → not found.
- **Collector unreachable or incomplete data**: run fails, failure cause recorded in last-run
  information, previous mapping retained.
- **Alpaca unreachable or credentials rejected**: run fails with an authentication/upstream error;
  previous mapping retained.
- **Lookup outcomes**: unmatched or ambiguous instruments return their stored record with status
  and reason; identifiers absent from the mapping return not found.
- **One symbol, several epics**: a matched Alpaca symbol belongs to at most one epic. If a run
  finds several epics passing for the same symbol, all of them are classified `ambiguous`
  (reason `symbol_conflict`, listing the competing epics), so a symbol lookup returns at most one
  epic.
- **Ambiguous epics**: an epic lookup returns status `ambiguous`, no Alpaca symbol, and the list of
  candidate symbols with their quality measures; a symbol lookup never returns ambiguous epics,
  so a symbol that appears only as an ambiguous candidate is reported as not found.
- **Schedule validation**: invalid cron, day range (e.g., `mon-xyz`), time (e.g., `25:00`), past
  one-time date, unknown timezone, or mixed formats → validation error; existing schedule kept.
- **Missed scheduled run** (service was stopped at the scheduled time): not executed retroactively;
  the next future occurrence is used. A one-time run whose instant passed while stopped is reported
  as missed and cleared.
- **Threshold file missing or invalid at startup**: service does not start.
- **Encryption key missing at startup**: service does not start.
- **Encryption key changed after credentials were stored**: credentials cannot be decrypted; runs
  fail with an error instructing the operator to update the credentials; update replaces the stored
  value without needing the old key.
- **Restart with active schedule**: schedule, timezone and last-run information survive.
- **Restart during a run**: on startup, any run still recorded as `running` is marked `failed` with
  cause "interrupted by service restart"; the previous mapping is kept, the run is not resumed or
  restarted automatically, and new runs are no longer blocked.

## Requirements *(mandatory)*

### Functional Requirements

**Matching process**

- **FR-001**: The system MUST implement the instrument matching process as its own capability,
  producing for every Capital.com US share epic in scope exactly one mapping record with a status of
  `matched` (with a match type of `exact` or `alias`), `ambiguous`, or `unmatched`.
- **FR-002**: The matching process MUST obtain Capital.com instruments and prices only through the
  collector service and Alpaca assets and prices only with the registered Alpaca credentials.
- **FR-003**: Each mapping record MUST include: epic, Alpaca symbol (when matched), status, price
  difference, direction agreement, return correlation, and a reason (category + human-readable
  detail) for unmatched or ambiguous records.
- **FR-004**: Match decisions MUST be governed by the thresholds loaded from the threshold
  configuration file at startup.
- **FR-005**: The system MUST NOT depend on the prototype at runtime or in its source code (no
  imports, file reads, paths, data or caches from it); it MUST start and operate with the prototype
  folder absent. The only exception is a one-time test baseline (prototype output for a fixed
  window, converted and committed under `tests/fixtures/reference_window/`) used solely to verify
  SC-006.

**Thresholds**

- **FR-006**: The system MUST load thresholds from a configuration file at startup and refuse to
  start if the file is missing or any value is missing, of the wrong type, or out of range.
- **FR-007**: Operators MUST be able to retrieve the thresholds currently in use, grouped by
  matching stage.

**Runs**

- **FR-008**: Operators MUST be able to start a matching run; the request MUST be acknowledged
  immediately with a run identifier while the run executes in the background. Run requests take no
  options: every run (manual or scheduled) covers the full instrument universe with the data window
  ending at the run's start time.
- **FR-009**: The system MUST allow at most one run at a time and reject or skip additional
  requests as described in Edge Cases.
- **FR-010**: A successful run MUST replace the stored mapping as a whole, atomically, so lookups
  never see a mix of old and new results.
- **FR-011**: A failed run MUST leave the previously stored mapping unchanged and record the
  failure cause.
- **FR-012**: The system MUST record, for the last run, its start time, end time, outcome
  (succeeded/failed), counts by status, and failure cause if any.
- **FR-012a**: Operators MUST be able to retrieve any retained run by its run identifier (trigger,
  state `running`/`succeeded`/`failed`, start and end time, counts by status, failure cause) and
  list recent runs newest first. At least the 50 most recent executed runs MUST be retained;
  skipped-run records (`skipped_concurrent_run`) are retained separately, at least the newest 20.
  An unknown or no-longer-retained run identifier MUST return a not-found error.
- **FR-012b**: At startup, the system MUST mark any run left in state `running` as `failed` with
  cause "interrupted by service restart", MUST NOT resume or automatically restart it, and MUST
  leave the stored mapping unchanged.

**Schedule**

- **FR-013**: Operators MUST be able to view the current schedule, next run time, last completed
  run time, and timezone, with all times expressed in the schedule's timezone.
- **FR-014**: Operators MUST be able to set a schedule in exactly one of three formats: standard
  5-field cron expression; recurring `day` + `time` (day as a single weekday, a range such as
  `mon-fri`, or a comma list; time as `HH:MM` 24-hour); or a single future `date` timestamp.
- **FR-015**: Operators MAY supply an IANA timezone; when omitted, the schedule MUST be interpreted
  as UTC (never the service timezone). The schedule view MUST express its times in the schedule's
  own timezone; the service timezone governs only other service output such as logs.
- **FR-016**: Setting the schedule to null MUST cancel all scheduled runs.
- **FR-017**: Requests that mix formats or contain invalid values MUST be rejected with a
  validation error naming the offending field, leaving the existing schedule unchanged.
- **FR-018**: Responses to a schedule change MUST confirm the applied schedule and the next run
  time.
- **FR-019**: The schedule, its timezone and last-run information MUST persist across restarts.
- **FR-020**: A one-time schedule MUST clear itself after it executes (or is missed).

**Lookup**

- **FR-021**: Consumers MUST be able to look up a mapping by exactly one of epic or Alpaca symbol;
  providing both or neither MUST return a validation error.
- **FR-022**: A lookup MUST return the stored mapping record(s) for that identifier, including
  status and quality measures, plus the time of the run that produced them.
- **FR-022a**: Ambiguous records MUST carry no Alpaca symbol but MUST list their candidate symbols
  with each candidate's quality measures; epic lookups return these candidates, and symbol lookups
  MUST return only `matched` records.
- **FR-023**: Unknown identifiers MUST return a not-found error distinct from a known-but-unmatched
  result.

**Credentials**

- **FR-024**: Operators MUST be able to register Alpaca credentials (key and secret) once and update
  them afterwards; both operations MUST return no content on success.
- **FR-025**: Credentials MUST be stored encrypted with the configured encryption key and MUST never
  be returned, logged or included in error messages in plain text.
- **FR-026**: Registering when credentials exist MUST return a conflict error; updating when none
  exist MUST return a not-found error.

**Access control**

- **FR-027**: In this version, no operation (operator or consumer) requires caller
  authentication; the service is reachable only from the internal network, and access protection
  is provided by that network boundary.

**Configuration, operation and errors**

- **FR-028**: The system MUST read its settings — collector location, database location and names,
  log level (INFO, DEBUG or WARNING), service timezone and encryption key — from an environment
  configuration file, and refuse to start if a required setting is missing or invalid.
- **FR-029**: The system MUST run directly from a terminal on a developer machine without
  containers.
- **FR-030**: All error responses MUST use a single, consistent structured error format with a
  meaningful status, title and detail.
- **FR-031**: The system MUST keep no request-spanning state in process memory; schedule, run
  status, mapping and credentials MUST live in the external data store.

**Documentation**

- **FR-032**: The service MUST ship documentation describing its matching process as implemented
  (stages, thresholds and their meaning, statuses and reason categories, known limitations),
  adapted from the prototype documentation and consistent with actual behavior.

### Key Entities

- **Instrument Mapping**: one record per Capital.com epic — epic, Alpaca symbol (optional), status
  (`matched`, `ambiguous`, `unmatched`), match type (`exact` or `alias`, matched records only),
  price difference, direction
  agreement, return correlation, reason category and detail, candidate symbols with their quality
  measures (ambiguous records only; symbol left empty), producing run identifier.
- **Matching Run**: one execution of the matching process — identifier, trigger (manual/scheduled),
  state (`running`, `succeeded`, `failed`), start and end time, failure cause, counts by status.
  The 50 most recent executed runs, plus the newest 20 skipped-run records, are retained and
  retrievable by identifier.
- **Schedule**: at most one active — format (cron, recurring, one-time), definition, timezone, next
  run time, last completed run time.
- **Threshold Set**: the matching thresholds loaded at startup, grouped by matching stage
  (candidate selection, data window, price check, behavior check).
- **Alpaca Credentials**: a single encrypted key/secret pair with registration and last-update
  times.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consumer translates any matched instrument in either direction with exactly one
  lookup, and 95% of lookups return in under 1 second.
- **SC-002**: After a schedule change, the operator immediately sees a next-run time that is correct
  in the configured timezone for 100% of the documented example schedules (cron, recurring,
  one-time, with and without timezone, including a daylight-saving transition).
- **SC-003**: Inspection of the data store reveals no plain-text Alpaca key or secret; 0 occurrences
  in stored data, responses and logs.
- **SC-004**: The service starts and completes a full matching run with the prototype folder
  removed.
- **SC-005**: A run triggered on demand is acknowledged in under 1 second; a full run over the US
  share universe completes in under 30 minutes.
- **SC-006**: On the same input data and thresholds, the service's results match the prototype's
  reference results for at least 99% of epics (status and symbol), with any differences explained
  in the documentation.
- **SC-007**: After a restart, 100% of schedule and last-run information is preserved and the next
  scheduled run fires at the expected time.
- **SC-008**: A failed run never reduces lookup availability: 100% of instruments resolvable before
  the failed run remain resolvable after it.

## Assumptions

- The scope of instruments is Capital.com US shares, as in the prototype; other asset classes are
  out of scope for this version.
- The matching process follows the prototype's stages (universe extraction, Alpaca asset retrieval,
  identifier then name candidates, common window, price check, behavior check, classification) and
  default thresholds; behavior may be refined where the documentation records the change.
- A successful run replaces the whole mapping snapshot; epics no longer present in the universe are
  removed. History of previous snapshots is not kept beyond the last-run summary.
- Lookups do not need Alpaca credentials; they serve the stored mapping.
- Missed scheduled runs are not executed retroactively.
- Partial or spot-check runs (epic subsets, custom window end) are out of scope for this version.
- Thresholds are read-only at runtime; changing them requires editing the file and restarting.
- A single Alpaca account (one credential pair) is used by the service.
- The service is deployed only on a trusted internal network; caller authentication is deferred to
  a future version. Because credentials are write-only, an unauthenticated caller can replace them
  but never read them.
- The collector service and its client package are available and handle Capital.com
  authentication.
- The external data store is reachable from the developer machine and holds mapping, runs,
  schedule and encrypted credentials.

## Clarifications

### Session 2026-10-18

- Q: If no timezone is given, does a schedule default to UTC or the service timezone, and which
  timezone does the schedule view use? → A: Default to UTC; the view uses the schedule's own
  timezone.
- Q: Should operator operations require authentication? → A: No authentication in this version;
  internal network only.
- Q: Besides the schedule view's "last run" details, can operators check a specific run's status
  by its identifier? → A: Yes — retrieve any retained run by identifier and list recent runs
  (newest first; at least the 50 most recent retained).
- Q: What happens to a run that was in progress when the service stopped or crashed? → A: On
  startup it is marked failed ("interrupted by service restart"); the previous mapping is kept;
  no automatic restart.
- Q: What does a lookup return for an ambiguous epic, and do symbol lookups find ambiguous
  epics? → A: Epic lookup returns ambiguous status with candidate symbols and no symbol; symbol
  lookups return confirmed matches only.
- Q: Can a run request take options (epic subset, window end), or is every run full? → A: No
  options; every run covers the full universe with the window ending at run start.
- Q: (planning) How is an exact match told apart from an alias match? → A: Status is
  `matched`/`ambiguous`/`unmatched`; matched records carry a separate match type `exact`/`alias`.
- Q: (planning) Can one Alpaca symbol be matched by several epics? → A: No; competing epics are all
  classified `ambiguous` with reason `symbol_conflict`.
- Q: (analysis) May the prototype's output be used as a test baseline? → A: Yes, once, as a
  committed fixture for SC-006; no runtime or source dependency.
