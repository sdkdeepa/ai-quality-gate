# PROJECT_STATE

Last updated: 2026-09-08 (Sprint 3 complete, manually validated)

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
        │   └── runner.py            # EvaluationRunner: dataset + provider -> EvaluationRun + CaseResults
        ├── providers/           # the internal provider interface + provider implementations
        │   ├── types.py             # ProviderRequest, ProviderResponse, ProviderError(Type)
        │   ├── base.py              # Provider protocol (name, model, generate)
        │   ├── cost.py              # CostCalculator protocol + TableCostCalculator + pricing tables
        │   ├── deterministic.py     # DeterministicProvider (wraps fixtures as a Provider)
        │   ├── openai_provider.py   # OpenAIProvider (only module importing `openai`)
        │   ├── gemini_provider.py   # GeminiProvider (only module importing `google.genai`)
        │   └── factory.py           # ProviderFactory: name -> Provider, resolves Settings/API keys
        ├── repositories/       # storage abstraction
        │   ├── base.py             # Repository protocol
        │   └── in_memory.py        # InMemoryRepository[T], InMemoryCaseResultStore
        ├── services/           # application/orchestration layer
        │   ├── status_service.py     # assembles /api/v1/status payload
        │   ├── dataset_service.py    # load/validate/list/get datasets + fixtures from disk
        │   └── evaluation_service.py # orchestrates dataset -> provider factory -> runner -> repositories
        ├── api/                 # HTTP layer (FastAPI routers)
        │   ├── deps.py              # FastAPI dependency providers
        │   ├── health.py            # GET /health
        │   ├── status.py            # GET /api/v1/status
        │   ├── datasets.py          # GET /api/v1/datasets, GET /api/v1/datasets/{name}/{version}
        │   └── evaluations.py       # POST /api/v1/evaluations/runs, GET /api/v1/evaluations/runs/{id}
        └── core/                 # cross-cutting concerns
            ├── config.py            # Settings (env-var driven, AQG_ prefix; dataset_dir + provider config)
            ├── context.py           # request-id ContextVar
            ├── logging.py           # JSON log formatter, configure_logging()
            ├── middleware.py        # RequestIDMiddleware (trace ID + timing)
            └── exceptions.py        # AppError family + exception handlers (incl. ProviderConfigurationError)
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

**Provider boundary (Sprint 3):** `app/providers/base.py` defines the
`Provider` protocol — `name`, `model`, `generate(ProviderRequest) ->
ProviderResponse`. `DeterministicProvider`, `OpenAIProvider`, and
`GeminiProvider` all implement it; `EvaluationRunner` and every `Evaluator`
depend only on this contract, never on the `openai` or `google.genai` SDKs
directly (those imports are confined to `openai_provider.py` and
`gemini_provider.py` respectively). Providers never raise for expected
failure modes (timeout, rate limit, unavailable, malformed response,
authentication) — they return a `ProviderResponse` with `error` set instead,
so one case failing to reach a live model never crashes an entire run.

## Completed capabilities (Sprint 1 + Sprint 2 + Sprint 3)

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

**Sprint 3 — Provider Abstraction, OpenAI and Gemini:**
- Provider contract (`app/providers/types.py`): `ProviderRequest`
  (case_id, prompt, system_prompt, json_schema, max_output_tokens,
  temperature) and `ProviderResponse` (provider, model, text,
  structured_output, retrieved_context, latency_ms, input/output tokens
  — optional, `estimated_cost` — optional, request_id — optional, error).
  `ProviderErrorType` normalizes every provider's failures onto 5 values:
  `timeout`, `rate_limit`, `unavailable`, `malformed_response`,
  `authentication`. A provider never raises for these — it returns a
  `ProviderResponse` with `error` set, so a single case's failure never
  aborts a run.
- `Provider` protocol (`app/providers/base.py`): `name`, `model`,
  `generate(request) -> response`. Three implementations:
  - `DeterministicProvider` — wraps the Sprint 2 fixture map
    (`dict[case_id, FixtureResponse]`) as a `Provider`. A run against it is
    byte-for-byte identical to Sprint 2's fixture-driven runner; it's the
    same fixture files wearing the Provider contract, not a parallel path.
  - `OpenAIProvider` — calls the OpenAI Chat Completions API (`openai`
    SDK). The only module allowed to import `openai`. Structured-output
    requests (`json_schema` set) ask for `response_format:
    {"type": "json_object"}` plus a schema-following instruction in the
    prompt; `structured_output` is a best-effort `json.loads` of the
    text — schema *compliance* is left to the existing
    `JSONSchemaEvaluator`, not re-validated in the provider.
  - `GeminiProvider` — calls the Gemini API (`google-genai` SDK, the
    `google.genai.Client.models.generate_content` surface). The only
    module allowed to import `google.genai`. Structured-output requests
    pass the case's JSON schema straight through via
    `response_json_schema` (Gemini accepts a schema directly, including a
    top-level array, unlike OpenAI's JSON-object mode).
  - Both live providers accept an injected SDK client for testing, catch
    every relevant SDK exception (`openai.APITimeoutError`,
    `AuthenticationError`, `RateLimitError`, `APIConnectionError`,
    `APIStatusError`, `OpenAIError`; `httpx.TimeoutException`,
    `google.genai.errors.ClientError/ServerError/APIError`) and map it to
    a `ProviderErrorType`; a response that can't be parsed (e.g. empty
    `choices`) becomes `malformed_response`.
- Cost calculation abstraction (`app/providers/cost.py`): `CostCalculator`
  protocol + `TableCostCalculator`, a static $/1M-token pricing table
  keyed by model name (`OPENAI_PRICING`, `GEMINI_PRICING`). An unknown
  model falls back to a configurable default price (0.0, 0.0) rather than
  raising — approximate, hand-maintained pricing, not a billing-API
  integration.
- `ProviderFactory` (`app/providers/factory.py`): builds a `Provider` by
  name (`"deterministic"` / `"openai"` / `"gemini"`), resolving API
  keys/models from `Settings`. Raises `ProviderConfigurationError` (400)
  for an unknown name or a live provider requested without its API key
  configured.
- `EvaluationRunner` (`app/evaluation/runner.py`) reframed around the
  provider contract: `run_with_provider(dataset, provider)` is now the
  core path (dataset → provider.generate() per case → EvaluationInput →
  evaluators), used for both live and fixture-backed runs. `run(dataset,
  fixtures)` is kept as a thin, behavior-identical convenience wrapper
  (upfront `MissingFixtureError` check, then a `DeterministicProvider`)
  so all Sprint 2 runner tests pass unchanged. When `ProviderResponse.error`
  is set, the case is recorded as a failed `CaseResult` (`passed=False`,
  `metric_results=[]`, `error` populated with `error_type`/`message`)
  without invoking any evaluator — a case that never reached the system
  under test has nothing for a deterministic evaluator to score.
- `CaseResult` (`app/domain/case_result.py`) gained one field: `error:
  dict[str, Any] | None`, carrying normalized provider error metadata for
  cases that failed at the provider level. `None` for every fixture-driven
  or successful-provider case — fully backward compatible.
- `EvaluationService.run(dataset_name, dataset_version, provider_name)`
  (renamed from `run_deterministic`, default `provider_name="deterministic"`
  preserves Sprint 2 behavior exactly) resolves the dataset, builds the
  requested provider via `ProviderFactory`, and delegates to
  `runner.run_with_provider`.
- API: `POST /api/v1/evaluations/runs` gained a `provider` field
  (`"deterministic" | "openai" | "gemini"`, default `"deterministic"`) on
  the request body; unknown values are rejected with 422 by FastAPI/Pydantic,
  a recognized-but-unconfigured provider with 400
  (`provider_not_configured`). Response shape is unchanged.
- New settings (`AQG_` prefix): `OPENAI_API_KEY`, `OPENAI_MODEL` (default
  `gpt-4o-mini`), `GEMINI_API_KEY`, `GEMINI_MODEL` (default
  `gemini-2.5-flash`), `PROVIDER_TIMEOUT_SECONDS` (default `30.0`).
- 58 new tests (174 total): provider contract tests parametrized across
  all three providers (mocked SDK clients for OpenAI/Gemini — no network
  calls), `DeterministicProvider` unit tests, per-provider normalized-
  failure tests (one per `ProviderErrorType`, plus a "never raises"
  assertion), `TableCostCalculator` tests, `ProviderFactory` tests
  (missing-key → `ProviderConfigurationError`), `run_with_provider`
  integration tests against a fake in-test `Provider` (including error →
  failed-`CaseResult` propagation and critical-case interaction), and API
  tests for the new `provider` request field. Two additional smoke tests
  (`tests/providers/test_smoke_real_apis.py`) make one real request each
  to OpenAI/Gemini but `skipif` unless `AQG_OPENAI_API_KEY` /
  `AQG_GEMINI_API_KEY` is set — they never run in ordinary `pytest`/CI.
- Explicitly out of scope per the sprint plan (deferred, not attempted):
  RAG, RAGAS, DeepEval, OpenAI Evals, Phoenix.

**Sprint 3 manual validation (2026-09-08):**
- Automated test suite: **COMPLETE** — 174 passed, 2 skipped (smoke tests).
- Linting: **COMPLETE**.
- `DeterministicProvider` manual validation via the running API: **COMPLETE**
  — confirmed matching Sprint 2 results (22 cases, 15 passed / 7 failed,
  critical failures `str-002`/`neg-001`) through `POST
  /api/v1/evaluations/runs` with `"provider": "deterministic"`.
- OpenAI real-provider smoke validation (`test_openai_smoke_real_request`,
  and a live `"provider": "openai"` run): **DEFERRED** — not a Sprint 3
  blocker; the smoke test remains in place (`tests/providers/
  test_smoke_real_apis.py`, `skipif` without `AQG_OPENAI_API_KEY`) for
  validation whenever an API key is available.
- Gemini real-provider smoke validation (`test_gemini_smoke_real_request`,
  and a live `"provider": "gemini"` run): **DEFERRED** — same as above,
  gated on `AQG_GEMINI_API_KEY`.

## Current sprint

Sprint 3 — Provider Abstraction, OpenAI and Gemini: **complete** (manually
validated 2026-09-08; real-provider smoke checks deferred, not blocking).

## Outstanding work (future sprints, not started)

- Real-provider smoke validation: run `uv run pytest -v -m smoke` (or a
  live `"provider": "openai"`/`"gemini"` API call) with
  `AQG_OPENAI_API_KEY`/`AQG_GEMINI_API_KEY` set — deferred at the end of
  Sprint 3, not yet done. Not a blocker for Sprint 4.
- RAG pipeline (LangChain + ChromaDB), retrieval metrics beyond the simple
  citation-presence check.
- Framework-backed evaluators (DeepEval, RAGAS, OpenAI Evals) implementing
  the same `Evaluator` protocol as the deterministic ones — groundedness/
  faithfulness, answer relevancy, context precision/recall.
- Release policy engine: thresholds config, baseline/regression comparison
  across runs, `GateDecision` computation (PASS/WARN/BLOCK) with audit
  trail — `GateDecision` exists as a domain model but nothing computes one
  yet; runs still only produce `CaseResult`s and run-level pass/fail counts.
- JSON/HTML evaluation report generation.
- Observability integration (Arize Phoenix).
- Persistent storage (repositories are in-memory only and reset on
  restart — no database yet).
- React engineering dashboard (frontend does not exist yet).
- Docker packaging and GitHub Actions CI.
- A `GET /api/v1/evaluations/runs` list endpoint (only "run" and "inspect
  one run" exist).
- Retries/backoff for transient live-provider failures (`rate_limit`,
  `unavailable`) — Sprint 3 normalizes and surfaces these but does not
  retry them; a case that hits one simply fails.
- Streaming, multi-turn conversation, and tool-calling support in
  `ProviderRequest`/`ProviderResponse` — Sprint 3's contract is single-turn,
  single-response only.

## Commands to run the project and tests

All commands run from `backend/`.

```bash
cd backend

# install dependencies (creates .venv via uv)
uv sync

# run the API locally (http://127.0.0.1:8000)
uv run uvicorn app.main:app --reload

# run the full test suite (live-API smoke tests self-skip without keys)
uv run pytest -v

# run only the live-API smoke tests (requires AQG_OPENAI_API_KEY/AQG_GEMINI_API_KEY;
# makes ONE real, cost-incurring request per key that's set)
uv run pytest -v -m smoke

# lint
uv run ruff check .

# format check / auto-format
uv run ruff format --check .
uv run ruff format .
```

Once running, in addition to Sprint 1/2's endpoints:

```bash
# list datasets
curl http://127.0.0.1:8000/api/v1/datasets

# inspect a dataset (full case list)
curl http://127.0.0.1:8000/api/v1/datasets/customer_support_bot/latest

# run evaluation with the deterministic (fixture-backed) provider — default, no API key needed
curl -X POST http://127.0.0.1:8000/api/v1/evaluations/runs \
  -H "Content-Type: application/json" \
  -d '{"dataset_name": "customer_support_bot"}'

# run evaluation against a live provider instead (requires AQG_OPENAI_API_KEY/
# AQG_GEMINI_API_KEY to be set when the server was started; incurs real API cost)
curl -X POST http://127.0.0.1:8000/api/v1/evaluations/runs \
  -H "Content-Type: application/json" \
  -d '{"dataset_name": "customer_support_bot", "provider": "openai"}'

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
| `AQG_OPENAI_API_KEY` | unset | OpenAI API key. Required to use `"provider": "openai"`; without it that provider returns 400 `provider_not_configured` |
| `AQG_OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name used by `OpenAIProvider` |
| `AQG_GEMINI_API_KEY` | unset | Gemini API key. Required to use `"provider": "gemini"`; without it that provider returns 400 `provider_not_configured` |
| `AQG_GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model name used by `GeminiProvider` |
| `AQG_PROVIDER_TIMEOUT_SECONDS` | `30.0` | Request timeout passed to the OpenAI/Gemini SDK clients |

Settings are also loadable from a `backend/.env` file (not committed).
