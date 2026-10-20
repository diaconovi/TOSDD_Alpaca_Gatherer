<!--
Sync Impact Report
==================
Version change: 1.0.0 → 1.0.1
Bump rationale: PATCH — Technology Stack wording; the Alpaca integration is no longer tied to one
SDK. No principle added, removed or redefined.

Modified sections:
  - Technology Stack & Constraints: "Alpaca APIs (via alpaca-py behind adapters)" → "Alpaca REST
    APIs through a typed adapter behind an application port (async HTTP client; SDKs optional)"

Added sections: none
Removed sections: none
Follow-up TODOs: none
-->

# Alpaca Market and Information API Microservice Constitution

## Core Principles

### I. Clean Code & Strict Static Typing

- All production and test code MUST be fully type-annotated (parameters, return values,
  attributes, module-level constants).
- Code MUST pass a static type checker in strict mode (e.g., `mypy --strict` or pyright
  `strict`) with zero errors. The chosen checker and its configuration MUST live in
  `pyproject.toml`.
- `Any`, untyped `# type: ignore`, and implicit `Optional` are prohibited unless a comment
  justifies the exception at the point of use (e.g., an untyped third-party boundary).
- Code MUST pass the configured linter/formatter (Ruff) with zero warnings.
- Functions and classes MUST have a single, clear responsibility; names MUST express intent;
  dead code, commented-out code, and duplicated logic MUST NOT be merged.

**Rationale**: Strict typing and lint gates catch defects before runtime and keep a financial
data service readable and safe to change.

### II. Modern Python & uv Toolchain

- The target runtime is **Python 3.14**. Code MUST use Python 3 syntax and idioms only
  (built-in generics such as `list[str]`, `X | None` unions, `match` where clearer,
  f-strings, `pathlib`); no Python 2 compatibility shims or `__future__`-era workarounds.
- `uv` is the sole tool for managing the Python version, dependencies, and the lockfile.
  Dependencies MUST be added/removed with `uv add` / `uv remove`; `uv.lock` MUST be committed.
  `pip install`, `requirements.txt`-only workflows, and global installs are prohibited.
- All work MUST happen inside the project virtual environment managed by uv (`.venv`).
- The application, tests, and tooling MUST be run through `uv run` (e.g., `uv run pytest`,
  `uv run python -m <package>`).

**Rationale**: A single toolchain guarantees reproducible environments across developer
machines and CI.

### III. Focused, Modular Library Design

- The project MUST remain a focused, modular Python package: each module owns one cohesive
  concern, and modules expose a small, explicit public API (`__all__` or documented entry
  points).
- Scope is limited to Alpaca market and information data; unrelated features MUST be rejected
  or placed in a separate package.
- Public modules, classes, and functions MUST have docstrings. Concise usage examples
  (doctest-style `>>>` blocks or short snippets) MUST be included where they clarify usage of
  a public API.

**Rationale**: Small, well-documented modules are easier to test, reuse, and reason about.

### IV. API-First & RESTful Conventions

- All business capabilities MUST be exposed through standardized RESTful HTTP endpoints;
  no business logic may be reachable only through internal scripts or ad-hoc entry points.
- Endpoints MUST be versioned under `/api/v{N}/` and use resource-oriented, plural,
  lowercase nouns (e.g., `/api/v1/assets`, `/api/v1/bars`). Verbs belong in HTTP methods,
  not paths.
- HTTP methods MUST follow their standard semantics (GET safe/idempotent, PUT/DELETE
  idempotent, POST for creation/actions).
- The API contract (e.g., OpenAPI) MUST be defined or updated before implementation and kept
  in sync with the code.

**Rationale**: A contract-first, predictable REST surface lets consumers integrate without
reading the implementation.

### V. Standardized Errors (RFC 7807)

- Every error response MUST be a JSON Problem Details payload per RFC 7807
  (`application/problem+json`) containing at least `type`, `title`, `status`, and `detail`,
  plus `instance` where applicable.
- HTTP status codes MUST be meaningful and accurate (e.g., 400 validation, 404 not found,
  409 conflict, 422 semantic errors, 502/503/504 for upstream failures); internal errors MUST
  NOT leak stack traces or secrets.
- Error mapping MUST be centralized in the interface layer, not scattered across handlers.

**Rationale**: Uniform errors make failures machine-handleable and debuggable for all clients.

### VI. Stateless Services

- Each service instance MUST be stateless: no session, user, or request-spanning state may be
  held in process memory between requests.
- Session or shared state MUST reside in an external distributed store (e.g., MongoDB or a
  dedicated cache), accessed through a repository interface.
- Any instance MUST be replaceable or horizontally scaled without data loss or behavior change.

**Rationale**: Statelessness enables horizontal scaling, safe restarts, and predictable
behavior.

### VII. Service Boundaries & Client Packages

- The service MUST NOT access another service's database or internal modules, and MUST NOT
  cross domain boundaries directly.
- Inter-service communication MUST occur only via explicit REST contracts or asynchronous
  events.
- Communication with another service MUST use that service's official client package.
  Registered clients:
  - **Collector** (Capital.com market, instruments, and prices gatherer):
    `to_collector_client`.
- Client packages MUST be wrapped behind an application-level port (see Principle VIII) so
  they can be faked in unit tests.

**Rationale**: Explicit contracts and shared clients keep services independently deployable
and prevent hidden coupling.

### VIII. Dependency Inversion

- The code base MUST follow a layered (clean/hexagonal) architecture: `domain` →
  `application` → `infrastructure` / `interface`. Dependencies MUST point inward only.
- `domain` MUST NOT import from `application`, `infrastructure`, `interface`, frameworks,
  or I/O libraries.
- Repositories, external API clients, caches, and clocks MUST be accessed through abstract
  interfaces (`typing.Protocol` or `abc.ABC`) defined in the inner layers and implemented in
  `infrastructure`.
- Concrete implementations MUST be wired at the composition root (application startup), not
  instantiated inside use cases.

**Rationale**: Inward-flowing dependencies isolate business rules from frameworks and vendors,
making them testable and replaceable.

### IX. Testing Discipline & Coverage

- Integration/contract tests are MANDATORY for every infrastructure database repository and
  every external HTTP client adapter (including Alpaca and `to_collector_client` adapters).
- Unit test line coverage for `domain` entities and `application` use cases MUST remain above
  80%; a change that drops coverage below this threshold MUST NOT be merged.
- Unit tests MUST NOT perform network or database I/O; they use fakes implementing the
  abstract interfaces.
- Tests are organized by layer and kind (`tests/unit/<layer>`, `tests/integration`,
  `tests/contract`) and run via `uv run pytest`.

**Rationale**: Contract tests protect boundaries with external systems; high unit coverage on
the core protects business behavior.

## Technology Stack & Constraints

- **Language/Runtime**: Python 3.14 (pinned via `.python-version` and `requires-python`).
- **Environment & dependencies**: uv, project-local `.venv`, committed `uv.lock`.
- **Quality tooling**: Ruff (lint + format), strict static type checker, pytest with coverage.
- **External integrations**: Alpaca REST APIs through a typed adapter behind an application
  port (async HTTP client; SDKs optional); Collector service via `to_collector_client` only.
- **State**: external distributed store (e.g., MongoDB); no in-process session state.
- **Secrets**: API keys and credentials MUST come from environment variables or a secret
  store, never from committed files.

## Development Workflow & Quality Gates

- Features follow the Spec Kit flow: specify → plan → tasks → implement. Each plan MUST
  include a Constitution Check against the principles above.
- Before merge, every change MUST pass, via `uv run`: Ruff lint/format check, strict type
  check, unit tests with the coverage gate (Principle IX), and the integration/contract tests
  relevant to touched adapters.
- API changes MUST update the API contract and include contract tests; breaking changes MUST
  introduce a new `/api/v{N+1}/` version.
- Code review MUST verify layer boundaries (Principle VIII), error format (Principle V), and
  statelessness (Principle VI).

## Governance

- This constitution supersedes all other development practices for this project. Where a
  guide or template conflicts with it, the constitution wins.
- **Amendments**: proposed via a change to `.specify/memory/constitution.md` with a written
  rationale and a migration note for affected code; adopted once approved by the project
  owner.
- **Versioning policy** (semantic versioning):
  - MAJOR: removal or backward-incompatible redefinition of a principle or governance rule.
  - MINOR: new principle/section or materially expanded guidance.
  - PATCH: clarifications, wording, or typo fixes with no semantic change.
- **Compliance review**: every plan and pull request MUST be checked against this
  constitution. Any deviation MUST be documented in the plan's Complexity Tracking section
  with justification and the simpler alternative that was rejected.

**Version**: 1.0.1 | **Ratified**: 2026-10-18 | **Last Amended**: 2026-10-18
