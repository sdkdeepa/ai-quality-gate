# PROJECT_STATE

Last updated: 2026-08-12 (Sprint 1 complete)

## Current architecture

```
ai-quality-gate/
├── PROJECT_STATE.md          # this file
├── DECISIONS.md               # architecture decision log
├── README.md
└── backend/
    ├── pyproject.toml         # uv-managed project, deps + ruff + pytest config
    ├── README.md
    └── app/
        ├── main.py             # FastAPI app factory (create_app), wires everything
        ├── domain/             # pure Pydantic domain models, no framework deps
        │   ├── enums.py            # ExpectedBehavior, RunStatus, GateStatus
        │   ├── evaluation_case.py  # EvaluationCase
        │   ├── evaluation_run.py   # EvaluationRun
        │   ├── metric_result.py    # MetricResult
        │   ├── case_result.py      # CaseResult
        │   └── gate_decision.py    # GateDecision
        ├── repositories/       # storage abstraction
        │   ├── base.py             # Repository protocol
        │   └── in_memory.py        # InMemoryRepository[T] (dict-backed, process-local)
        ├── services/           # application/orchestration layer
        │   └── status_service.py   # assembles /api/v1/status payload
        ├── api/                 # HTTP layer (FastAPI routers)
        │   ├── deps.py              # FastAPI dependency providers
        │   ├── health.py            # GET /health
        │   └── status.py            # GET /api/v1/status
        └── core/                 # cross-cutting concerns
            ├── config.py            # Settings (env-var driven, AQG_ prefix)
            ├── context.py           # request-id ContextVar
            ├── logging.py           # JSON log formatter, configure_logging()
            ├── middleware.py        # RequestIDMiddleware (trace ID + timing)
            └── exceptions.py        # AppError/NotFoundError + exception handlers
```

**Layering principle in effect:** domain models have zero framework
dependencies (pure Pydantic); repositories only know about domain models;
services compose repositories + config; the API layer is the only place that
knows about FastAPI/HTTP. This separation is intentionally light — there is
no repository interface per aggregate, no CQRS, no DI container. Just enough
seams to swap in-memory storage for a real database later without touching
domain or API code.

**Plugin boundary (not yet built, but the reason for this layering):**
Evaluation frameworks (DeepEval, RAGAS, OpenAI Evals, LangChain, Phoenix) will
sit behind an internal evaluation interface and only ever produce
`MetricResult` objects. The Quality Gate — not any framework — owns
orchestration, thresholds, baseline comparison, and the `GateDecision`
(PASS/WARN/BLOCK). Nothing in Sprint 1 violates this boundary because no
framework integrations exist yet.

## Completed capabilities (Sprint 1)

- Domain model: `EvaluationCase`, `EvaluationRun`, `MetricResult`,
  `CaseResult`, `GateDecision` — all Pydantic v2 models with field
  validation (non-blank required fields, non-negative numerics, finite
  scores, timestamp ordering, enum-constrained status fields).
- FastAPI application factory (`app.main.create_app`) with:
  - `GET /health` — liveness check.
  - `GET /api/v1/status` — app name/version/environment/uptime + in-memory
    repository counts.
- Configuration via environment variables (`AQG_` prefix) using
  `pydantic-settings`.
- Structured JSON logging (`app.core.logging.configure_logging`) — every log
  line is a single JSON object with timestamp/level/logger/message and the
  active request ID when available.
- Request/trace ID middleware (`RequestIDMiddleware`) — generates or
  propagates `X-Request-ID`, stores it in a `ContextVar` so logs and error
  bodies can include it, echoes it back on the response header.
- Application exception handling: `AppError`/`NotFoundError` base classes,
  handlers for `AppError`, `RequestValidationError`, and unhandled
  exceptions, all returning a consistent `{"error": {code, message,
  request_id}}` body. Unhandled exceptions are logged with full traceback
  server-side but never leak details to the client.
- Domain/service/repository separation: `InMemoryRepository[T]` generic
  repository, `StatusService` as the one example service composing
  repositories + settings.
- PyTest suite: 37 tests — domain validation unit tests (one file per
  domain model + repository), API tests for `/health`, `/api/v1/status`,
  and the exception-handling behavior.
- Ruff configured and passing (lint + format check clean).

## Current sprint

Sprint 1 — Foundation and Domain Model: **complete**.

## Outstanding work (future sprints, not started)

- Model provider integrations (OpenAI, Gemini/Vertex AI, deterministic test
  provider) and the internal provider interface.
- RAG pipeline (LangChain + ChromaDB), retrieval metrics.
- Evaluation framework plugins (DeepEval, RAGAS, OpenAI Evals) behind the
  internal evaluation interface — frameworks emit `MetricResult`s only.
- Evaluation orchestration service that runs an `EvaluationRun` over a
  golden dataset and produces `CaseResult`s.
- Release policy engine: thresholds config, critical-case handling,
  baseline/regression comparison, `GateDecision` computation with audit
  trail.
- Golden dataset versioning and loading (currently no dataset storage or
  file format exists).
- JSON/HTML evaluation report generation.
- Observability integration (Arize Phoenix).
- Persistent storage (repositories are in-memory only and reset on
  restart — no database yet).
- React engineering dashboard (frontend does not exist yet).
- Docker packaging and GitHub Actions CI.
- API/integration tests beyond health/status once real endpoints exist
  (e.g., `POST` endpoints for cases/runs — not built yet, so no CRUD API
  exists beyond the two read-only endpoints above).

## Commands to run the project and tests

All commands run from `backend/`.

```bash
cd backend

# install dependencies (creates .venv via uv)
uv sync

# run the API locally (http://127.0.0.1:8000)
uv run uvicorn app.main:app --reload

# run the full test suite
uv run pytest -v

# lint
uv run ruff check .

# format check / auto-format
uv run ruff format --check .
uv run ruff format .
```

Once running, `GET /health`, `GET /api/v1/status`, and interactive API docs
at `/docs` (OpenAPI at `/openapi.json`) are available.

## Important environment variables

All are optional; sane defaults are used if unset. Prefix: `AQG_`.

| Variable | Default | Purpose |
|---|---|---|
| `AQG_APP_NAME` | `AI Quality Gate` | Displayed app name (used in `/api/v1/status`) |
| `AQG_VERSION` | `0.1.0` | Reported app version |
| `AQG_ENVIRONMENT` | `development` | Environment label (`development`/`staging`/`production`) |
| `AQG_LOG_LEVEL` | `INFO` | Root logger level |
| `AQG_API_V1_PREFIX` | `/api/v1` | Prefix under which v1 routers are mounted |

Settings are also loadable from a `backend/.env` file (not committed).
