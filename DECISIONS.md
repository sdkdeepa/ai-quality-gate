# DECISIONS

Architecture decision log for the AI Quality Gate. Newest entries at the
bottom of each sprint's section. Each entry: decision, reason, alternatives
considered, trade-off.

## Sprint 1 — Foundation and Domain Model

### 1. Evaluation frameworks are plugins; the Gate owns policy

**Decision:** Domain models (`EvaluationCase`, `EvaluationRun`,
`MetricResult`, `CaseResult`, `GateDecision`) are defined independently of
any evaluation framework and contain no DeepEval/RAGAS/OpenAI Evals/Phoenix
types or imports. `MetricResult` is a normalized, framework-agnostic shape
that any plugin must translate its output into.

**Reason:** The system's core value is a stable, auditable release policy.
If DeepEval or RAGAS types leaked into the domain model, a framework
upgrade or swap would force changes to policy logic, thresholds, and audit
records — the parts that must be most stable and most trustworthy.

**Alternatives considered:** Model `MetricResult` directly on top of one
framework's native result type (e.g., DeepEval's) to save translation code.

**Trade-off:** Slightly more integration code later (a mapping layer per
framework). In exchange, thresholds/policy/audit logic never depend on a
third-party library's internal representation, and multiple frameworks can
score the same case without conflict.

### 2. Pydantic v2 models as the domain layer (no separate ORM/DB models yet)

**Decision:** Domain entities are plain Pydantic `BaseModel` classes in
`app/domain/`, with no ORM, dataclass, or attrs alternative.

**Reason:** Pydantic v2 gives validation, JSON (de)serialization, and
OpenAPI schema generation for free, and FastAPI already requires it as a
dependency. For Sprint 1 (no persistent database), introducing a second
model layer (ORM entities distinct from API/domain models) would be pure
overhead with no current benefit.

**Alternatives considered:** `dataclasses` + manual validation (less
built-in validation, no automatic JSON schema); SQLAlchemy declarative
models from day one (couples domain to a specific persistence technology
before persistence is even needed).

**Trade-off:** When a real database is introduced, a translation layer
between Pydantic domain models and ORM/table rows will likely be needed
(or a library like SQLModel that unifies them). Deferred deliberately —
YAGNI until persistence is actually built.

### 3. In-memory repositories behind a `Repository` protocol

**Decision:** `app/repositories/base.py` defines a minimal `Repository`
`Protocol` (add/get/list/delete/count). `InMemoryRepository[T]` is the only
implementation, generic over any Pydantic model with an `id` field.

**Reason:** The user's spec explicitly asked for in-memory repositories in
Sprint 1 while preserving domain/service/repository separation. A
`Protocol` (structural typing) rather than an ABC keeps the seam cheap:
no inheritance required, easy to fulfill with a future SQL-backed
implementation.

**Alternatives considered:** No repository abstraction at all (services
hold raw dicts) — rejected because it would make swapping in real
persistence later a larger, riskier change. A full generic
Unit-of-Work/Session pattern — rejected as over-engineering for a
single-process, single-collection use case at this stage.

**Trade-off:** The `Repository` protocol is currently unused for dispatch
(only one implementation exists), so its value is speculative until a
second backend is built. Accepted because the cost (one small file) is low
and it documents intent.

### 4. Structured JSON logging + request-ID `ContextVar`, not a logging library

**Decision:** Logging is configured with the Python standard library
(`logging` + a custom `JSONFormatter`), and the request/trace ID is
threaded through a `contextvars.ContextVar` rather than passed explicitly
or stored on `request.state` alone.

**Reason:** JSON logs are a prerequisite for the "auditable release
decisions" requirement later (structured, queryable logs). A `ContextVar`
lets any code — including code with no direct access to the `Request`
object (e.g., a future background evaluation worker) — pick up the current
request ID for correlation.

**Alternatives considered:** `structlog` or `python-json-logger` — good
libraries, but an extra dependency for something ~40 lines of stdlib code
can provide at this stage. Passing `request_id` as an explicit parameter
through every function call — rejected as excessive plumbing for a
cross-cutting concern.

**Trade-off:** Hand-rolled JSON formatter is less feature-rich than
`structlog` (no built-in processors, no contextual binding helpers). If
logging needs grow (log sampling, multiple sinks, structured exception
grouping), revisit and likely adopt `structlog` then.

### 5. `AppError` exception hierarchy + centralized handlers over per-route try/except

**Decision:** A small `AppError` base exception (with `status_code` and
`code`) and subclasses like `NotFoundError` are raised from application
code; three handlers (`AppError`, `RequestValidationError`, generic
`Exception`) are registered once in `create_app()` and produce a
consistent `{"error": {code, message, request_id}}` body.

**Reason:** Keeps route/service code focused on business logic (`raise
NotFoundError(...)`) instead of manually constructing `JSONResponse`
objects everywhere, and guarantees every error — expected or not —
returns the same shape and includes the request ID for audit/correlation.
The generic `Exception` handler also ensures internal details never leak
to API clients.

**Alternatives considered:** Returning `Optional`/result types from
services and having routes check them — more verbose at every call site
and doesn't help with truly unexpected exceptions. FastAPI's default
unhandled-exception behavior (raw 500, framework-specific body) — rejected
because it's inconsistent with the validation-error and app-error bodies.

**Trade-off:** All application errors must go through this hierarchy to
get consistent formatting; ad hoc `HTTPException` usage elsewhere would
break the contract, so this needs to stay a convention the team follows.

### 6. Environment-variable configuration via `pydantic-settings`, prefix `AQG_`

**Decision:** A single `Settings` class (`pydantic-settings` `BaseSettings`)
with an `AQG_` env var prefix, cached via `lru_cache`-wrapped
`get_settings()`.

**Reason:** Standard, typed, validated configuration with minimal code;
the prefix avoids collisions with other env vars (`PORT`, `LOG_LEVEL`,
etc.) that might be set by a hosting platform or CI.

**Alternatives considered:** Raw `os.environ.get(...)` calls scattered
across modules — no validation, no single source of truth, easy to typo a
key. A YAML/TOML config file — deferred; env vars are sufficient for
Sprint 1's small settings surface and match the eventual Docker/CI
deployment model.

**Trade-off:** None significant at this scale; revisit only if config
grows large enough to need nested structured config (at which point a
config file + env override pattern would be added).

### 7. `uv` for dependency management over `poetry`/`pip-tools`

**Decision:** Backend uses `uv` (`pyproject.toml` + `uv.lock`) for
dependency resolution, virtualenv management, and running tests/lint.

**Reason:** `uv` was already installed and available in the target
environment; `poetry` was not. `uv` is fast, single-binary, and Docker
images in a later sprint can use the official `uv` base image or `pip
install uv` without extra tooling.

**Alternatives considered:** `poetry` (not installed, would add a setup
step for no functional benefit); plain `pip` + `requirements.txt` (no
lockfile-based reproducibility by default).

**Trade-off:** Team members must have `uv` installed locally (or use
`pipx run uv`); this is a minor onboarding step noted in
`PROJECT_STATE.md`.
