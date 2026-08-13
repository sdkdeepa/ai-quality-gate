# PROJECT_STATE

Last updated: 2026-08-12 (Sprint 2 complete)

## Current architecture

```
ai-quality-gate/
├── PROJECT_STATE.md          # this file
├── DECISIONS.md               # architecture decision log
├── README.md
└── backend/
    ├── pyproject.toml         # uv-managed project, deps + ruff + pytest config
    ├── README.md
    ├── datasets/               # versioned golden dataset JSON files (data, not code)
    │   ├── customer_support_bot.v1.0.0.json           # 22-case seed golden dataset
    │   └── customer_support_bot.v1.0.0.fixtures.json  # deterministic fixture responses
    └── app/
        ├── main.py             # FastAPI app factory (create_app), wires everything
        ├── domain/             # pure Pydantic domain models, no framework deps
        │   ├── enums.py            # ExpectedBehavior, RunStatus, GateStatus
        │   ├── evaluation_case.py  # EvaluationCase
        │   ├── evaluation_run.py   # EvaluationRun
        │   ├── metric_result.py    # MetricResult
        │   ├── case_result.py      # CaseResult
        │   ├── gate_decision.py    # GateDecision
        │   └── golden_dataset.py   # GoldenDataset (name/version/created_at/description/cases) + semver_key
        ├── evaluation/          # the internal evaluation interface + deterministic plugin
        │   ├── base.py              # Evaluator protocol (applies_to + evaluate -> MetricResult)
        │   ├── types.py             # EvaluationInput, FixtureResponse
        │   ├── deterministic.py     # 8 deterministic evaluators + DEFAULT_EVALUATORS
        │   └── runner.py            # EvaluationRunner: dataset + fixtures -> EvaluationRun + CaseResults
        ├── repositories/       # storage abstraction
        │   ├── base.py             # Repository protocol
        │   └── in_memory.py        # InMemoryRepository[T], InMemoryCaseResultStore
        ├── services/           # application/orchestration layer
        │   ├── status_service.py     # assembles /api/v1/status payload
        │   ├── dataset_service.py    # load/validate/list/get datasets + fixtures from disk
        │   └── evaluation_service.py # orchestrates dataset -> runner -> repositories
        ├── api/                 # HTTP layer (FastAPI routers)
        │   ├── deps.py              # FastAPI dependency providers
        │   ├── health.py            # GET /health
        │   ├── status.py            # GET /api/v1/status
        │   ├── datasets.py          # GET /api/v1/datasets, GET /api/v1/datasets/{name}/{version}
        │   └── evaluations.py       # POST /api/v1/evaluations/runs, GET /api/v1/evaluations/runs/{id}
        └── core/                 # cross-cutting concerns
            ├── config.py            # Settings (env-var driven, AQG_ prefix; adds dataset_dir)
            ├── context.py           # request-id ContextVar
            ├── logging.py           # JSON log formatter, configure_logging()
            ├── middleware.py        # RequestIDMiddleware (trace ID + timing)
            └── exceptions.py        # AppError family + exception handlers
```

**Layering principle in effect:** domain models have zero framework
dependencies (pure Pydantic); repositories only know about domain models;
services compose repositories + config; the API layer is the only place that
knows about FastAPI/HTTP. This separation is intentionally light — there is
no repository interface per aggregate, no CQRS, no DI container. Just enough
seams to swap in-memory storage for a real database later without touching
domain or API code.

**Plugin boundary (now proven, not just planned):** `app/evaluation/base.py`
defines the `Evaluator` protocol — `applies_to(case)` + `evaluate(input) ->
MetricResult`. The 8 deterministic evaluators in `app/evaluation/deterministic.py`
are the first (and so far only) implementation of that protocol. They know
nothing about HTTP, datasets-on-disk, or release policy — they take an
`EvaluationInput` and return a normalized `MetricResult`. `EvaluationRunner`
composes evaluators against a dataset's cases; it does **not** compute a
PASS/WARN/BLOCK decision — that remains future work for the Gate's policy
layer. When DeepEval/RAGAS/OpenAI Evals/Phoenix are integrated in a later
sprint, they will implement this same `Evaluator` protocol side-by-side with
the deterministic ones, proving the plugin boundary rather than just
asserting it.

## Completed capabilities (Sprint 1 + Sprint 2)

**Sprint 1 — Foundation:**
- Domain model: `EvaluationCase`, `EvaluationRun`, `MetricResult`,
  `CaseResult`, `GateDecision` — Pydantic v2 models with field validation.
- FastAPI app factory, `GET /health`, `GET /api/v1/status`.
- Env-var configuration (`AQG_` prefix, `pydantic-settings`), structured
  JSON logging, request/trace-ID middleware, centralized `AppError`
  exception handling with a consistent `{"error": {...}}` body.
- `InMemoryRepository[T]`, domain/service/repository separation.
- 37 tests (domain validation + health/status API + error handling).

**Sprint 2 — Golden Dataset and Deterministic Evaluation:**
- `GoldenDataset` domain model: `name`, semver `version` (validated
  `X.Y.Z`), `created_at`, `description`, `cases: list[EvaluationCase]`.
  Rejects empty case lists, duplicate case ids within a dataset, blank
  name/description, and non-semver versions.
- Dataset file format: one JSON file per version,
  `{name}.v{version}.json`; loaded from `backend/datasets/` (configurable
  via `AQG_DATASET_DIR`). A sibling `{name}.v{version}.fixtures.json` maps
  case id → a deterministic `FixtureResponse` (response text, retrieved
  context, latency, tokens, cost) used by the evaluation runner in place of
  a live model provider (none exists yet).
- Seed dataset `customer_support_bot` v1.0.0 — **22 cases**: 5 answerable,
  4 unsupported/out-of-scope, 3 expected-refusal, 3 structured-output
  (JSON schema), 4 retrieval-grounded, 3 negative/adversarial. **6 cases
  flagged `critical=true`** spanning every category. Fixtures are crafted
  so the run has a realistic mix: **15 passing / 7 failing**, with exactly
  one deliberate failure exercised per evaluator type, and **2 critical
  failures** (`str-002`: malformed structured output; `neg-001`: a
  successful prompt-injection leak) to prove critical-case detection works
  end to end.
- `DatasetService` (`app/services/dataset_service.py`): `load_all()`,
  `list_datasets()`, `get_dataset(name, version | "latest")`,
  `get_fixtures(dataset)`. Malformed JSON or schema-invalid datasets raise
  `DatasetValidationError` (422) naming the offending file; missing/invalid
  fixtures raise `FixtureValidationError` (422). `parse_dataset()` is a
  standalone function usable directly in tests without touching disk.
- Internal evaluation interface (`app/evaluation/base.py`): `Evaluator`
  protocol — `applies_to(case) -> bool`, `evaluate(input) -> MetricResult`.
  Applicability is data-driven from case fields/metadata ("where
  appropriate"), not hardcoded per category.
- 8 deterministic evaluators (`app/evaluation/deterministic.py`), all
  framework=`"deterministic"`:
  `ExactMatchEvaluator` (normalized match, opt-in via
  `metadata.match_mode="exact"`), `RequiredPhraseEvaluator`,
  `ForbiddenPhraseEvaluator`, `JSONSchemaEvaluator` (via `jsonschema`),
  `ExpectedRefusalEvaluator` (refusal-language detection for
  REFUSE/UNSUPPORTED cases), `CitationPresenceEvaluator` (retrieval cases
  must return retrieved context), `LatencyThresholdEvaluator`,
  `CostThresholdEvaluator` (both with a global default, overridable per
  case via metadata).
- `EvaluationRunner` (`app/evaluation/runner.py`): runs a `GoldenDataset`
  against a `dict[case_id, FixtureResponse]`, applies only the evaluators
  relevant to each case, produces `CaseResult`s and a completed
  `EvaluationRun`. Raises `MissingFixtureError` (400) if any case lacks a
  fixture. `critical_failure` is set exactly when `case.critical and not
  passed`.
- `EvaluationService` orchestrates dataset resolution → fixture loading →
  run → persistence (`EvaluationRun` in `InMemoryRepository`, `CaseResult`s
  in the new `InMemoryCaseResultStore`, keyed by run id).
- API endpoints:
  - `GET /api/v1/datasets` — summary list (name/version/description/
    created_at/case_count) of every loaded dataset.
  - `GET /api/v1/datasets/{name}/{version}` — full dataset incl. all
    cases; `version="latest"` resolves to the newest semver.
  - `POST /api/v1/evaluations/runs` — body `{dataset_name, dataset_version?}`,
    runs the deterministic evaluators against the dataset's fixtures,
    returns a run summary (status, case/passed/failed counts, critical
    failure case ids).
  - `GET /api/v1/evaluations/runs/{run_id}` — full run detail including
    every case's `metric_results`.
- 116 tests total (79 new in Sprint 2): dataset domain validation,
  8-evaluator unit tests (`applies_to` + pass/fail per evaluator),
  runner tests (completion, missing fixture, critical-failure flagging),
  `DatasetService` tests incl. malformed-JSON/schema-violation rejection
  via `tmp_path` fixtures, dataset + evaluation API tests, and a dedicated
  critical-case test module that runs the real seed dataset through the
  service/runner layer (no HTTP) and asserts on all 6 critical cases by id.
- Fixed a pre-existing deprecation: `status.HTTP_422_UNPROCESSABLE_ENTITY`
  → `status.HTTP_422_UNPROCESSABLE_CONTENT` (Starlette rename), applied
  everywhere in `core/exceptions.py`.

## Current sprint

Sprint 2 — Golden Dataset and Deterministic Evaluation: **complete**.

## Outstanding work (future sprints, not started)

- Model provider integrations (OpenAI, Gemini/Vertex AI, deterministic test
  provider) and the internal provider interface — the evaluation runner
  currently only consumes pre-recorded fixtures, never calls a live model.
- RAG pipeline (LangChain + ChromaDB), retrieval metrics beyond the simple
  citation-presence check.
- Framework-backed evaluators (DeepEval, RAGAS, OpenAI Evals) implementing
  the same `Evaluator` protocol as the deterministic ones — groundedness/
  faithfulness, answer relevancy, context precision/recall.
- Release policy engine: thresholds config, baseline/regression comparison
  across runs, `GateDecision` computation (PASS/WARN/BLOCK) with audit
  trail — `GateDecision` exists as a domain model but nothing computes one
  yet; Sprint 2 only produces `CaseResult`s and run-level pass/fail counts.
- JSON/HTML evaluation report generation.
- Observability integration (Arize Phoenix).
- Persistent storage (repositories are in-memory only and reset on
  restart — no database yet).
- React engineering dashboard (frontend does not exist yet).
- Docker packaging and GitHub Actions CI.
- A `GET /api/v1/evaluations/runs` list endpoint (only "run" and "inspect
  one run" exist; listing all runs wasn't in Sprint 2's scope).

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

Once running, in addition to Sprint 1's endpoints:

```bash
# list datasets
curl http://127.0.0.1:8000/api/v1/datasets

# inspect a dataset (full case list)
curl http://127.0.0.1:8000/api/v1/datasets/customer_support_bot/latest

# run deterministic evaluation
curl -X POST http://127.0.0.1:8000/api/v1/evaluations/runs \
  -H "Content-Type: application/json" \
  -d '{"dataset_name": "customer_support_bot"}'

# inspect a run (use the "id" from the response above)
curl http://127.0.0.1:8000/api/v1/evaluations/runs/<run_id>
```

Interactive API docs at `/docs` (OpenAPI at `/openapi.json`).

## Important environment variables

All are optional; sane defaults are used if unset. Prefix: `AQG_`.

| Variable | Default | Purpose |
|---|---|---|
| `AQG_APP_NAME` | `AI Quality Gate` | Displayed app name (used in `/api/v1/status`) |
| `AQG_VERSION` | `0.1.0` | Reported app version |
| `AQG_ENVIRONMENT` | `development` | Environment label (`development`/`staging`/`production`) |
| `AQG_LOG_LEVEL` | `INFO` | Root logger level |
| `AQG_API_V1_PREFIX` | `/api/v1` | Prefix under which v1 routers are mounted |
| `AQG_DATASET_DIR` | `datasets` | Directory of golden dataset JSON files; relative paths resolve against `backend/` |

Settings are also loadable from a `backend/.env` file (not committed).
