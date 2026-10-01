# DECISIONS

Concise architectural decision record. Detailed implementation behavior is documented in the code and focused project docs; this file records the non-obvious choices that shaped the system.

## Sprint 1 — Foundation and Domain Model

### 1. Evaluation frameworks are plugins; the Gate owns policy

Domain models (`EvaluationCase`, `EvaluationRun`, `MetricResult`, `CaseResult`, `GateDecision`) are defined independently of any evaluation framework and contain no DeepEval/RAGAS/OpenAI Evals/Phoenix types or imports. `MetricResult` is a normalized, framework-agnostic shape that any plugin must translate its output into.

### 2. Pydantic v2 models as the domain layer (no separate ORM/DB models yet)

Domain entities are plain Pydantic `BaseModel` classes in `app/domain/`, with no ORM, dataclass, or attrs alternative.

### 3. In-memory repositories behind a `Repository` protocol

`app/repositories/base.py` defines a minimal `Repository` `Protocol` (add/get/list/delete/count). `InMemoryRepository[T]` is the only implementation, generic over any Pydantic model with an `id` field.

### 4. Structured JSON logging + request-ID `ContextVar`, not a logging library

Logging is configured with the Python standard library (`logging` + a custom `JSONFormatter`), and the request/trace ID is threaded through a `contextvars.ContextVar` rather than passed explicitly or stored on `request.state` alone.

### 5. `AppError` exception hierarchy + centralized handlers over per-route try/except

A small `AppError` base exception (with `status_code` and `code`) and subclasses like `NotFoundError` are raised from application code; three handlers (`AppError`, `RequestValidationError`, generic `Exception`) are registered once in `create_app()` and produce a consistent `{"error": {code, message, request_id}}` body.

### 6. Environment-variable configuration via `pydantic-settings`, prefix `AQG_`

A single `Settings` class (`pydantic-settings` `BaseSettings`) with an `AQG_` env var prefix, cached via `lru_cache`-wrapped `get_settings()`.

### 7. `uv` for dependency management over `poetry`/`pip-tools`

Backend uses `uv` (`pyproject.toml` + `uv.lock`) for dependency resolution, virtualenv management, and running tests/lint.

## Sprint 2 — Golden Dataset and Deterministic Evaluation

### 8. Evaluators are data-driven ("applies_to"), not category-hardcoded

The `Evaluator` protocol requires both `applies_to(case) -> bool` and `evaluate(input) -> MetricResult`. Whether an evaluator runs for a given case is decided by inspecting the case's own fields/metadata (e.g. `RequiredPhraseEvaluator` applies iff `metadata["required_phrases"]` is non-empty; `ExpectedRefusalEvaluator` applies iff `expected_behavior` is `REFUSE`/`UNSUPPORTED`) rather than a runner-level `if category == "structured_output": run JSONSchemaEvaluator` dispatch table.

### 9. Evaluators never compute pass/fail policy beyond their own metric

Each evaluator returns exactly one `MetricResult` with its own `score`/`threshold`/`passed`. `EvaluationRunner` combines them for a case via a simple `passed = all(m.passed for m in metric_results)` — no weighting, no partial credit across metrics, no evaluator-specific override of what "case passed" means.

### 10. Fixture-driven runner instead of a fake/mock model provider

`EvaluationRunner.run()` takes a `dict[case_id, FixtureResponse]` of pre-recorded responses rather than calling any provider interface (real or fake). `DatasetService.get_fixtures()` loads these from a `{name}.v{version}.fixtures.json` file that sits alongside the dataset file.

### 11. Dataset/fixture files on disk, not in a database or embedded in code

Golden datasets and their fixtures are plain JSON files under `backend/datasets/`, loaded by `DatasetService.load_all()` at app startup into the existing `InMemoryRepository[GoldenDataset]`. Naming convention `{name}.v{version}.json` / `{name}.v{version}.fixtures.json` encodes versioning in the filename rather than a database column.

## Sprint 3 — Provider Abstraction, OpenAI and Gemini

### 12. Providers normalize failures into the response instead of raising

`Provider.generate()` never raises for the five defined failure modes (`timeout`, `rate_limit`, `unavailable`, `malformed_response`, `authentication`). `OpenAIProvider` and `GeminiProvider` catch every relevant SDK exception internally and return a `ProviderResponse` with `error` set instead; `EvaluationRunner` checks `response.error` and records a failed `CaseResult` rather than letting an exception propagate.

### 13. `DeterministicProvider` reframes Sprint 2's fixtures, rather than adding a parallel path

`DeterministicProvider` takes the exact same `dict[case_id, FixtureResponse]` `DatasetService.get_fixtures()` already produced in Sprint 2 and wraps it as a `Provider`. `EvaluationRunner.run(dataset, fixtures)` — the Sprint 2 entry point — is kept, but is now a thin wrapper that builds a `DeterministicProvider` and delegates to the new `run_with_provider(dataset, provider)`, which is what `OpenAIProvider`/ `GeminiProvider` runs also go through.

### 14. Cost calculation is a pluggable, static pricing-table lookup, not a billing-API integration

`TableCostCalculator` estimates cost from a hand-maintained `dict[model, (input_price_per_1m, output_price_per_1m)]`, injected into each live provider (defaulting to `OPENAI_PRICING`/`GEMINI_PRICING`). An unrecognized model name returns a configurable default price (`(0.0, 0.0)`) instead of raising.

### 15. Provider selection is a per-request field, resolved through a factory — not fixed at process startup

`POST /api/v1/evaluations/runs` takes a `provider` field (`"deterministic" | "openai" | "gemini"`, default `"deterministic"`). `ProviderFactory.create(provider_name, dataset=...)` builds the requested `Provider` per call, reading API keys/models from `Settings` and raising `ProviderConfigurationError` (400) if a live provider is requested without its key configured.

## Sprint 4 — Sample RAG System using LangChain and ChromaDB

### 16. The RAG system is a system under test, not part of the Quality Gate

`app/rag/` is a self-contained sample application — a real retrieve-then-generate pipeline over a small local corpus — built specifically to give the Gate something realistic to evaluate. It is not a chat feature, not a product surface, and the Gate's own evaluation code (`app/evaluation/`, the release-policy layer this is all in service of) never imports anything from `app/rag/`. The dependency direction is one-way: `app/rag` depends on `app/providers` (for generation) exactly the way any other system-under-test would; nothing in the Gate depends on `app/rag`.

### 17. Where LangChain is used, and where our own code takes over

LangChain provides three things, and three things only:

### 18. `RAGProvider` adapts the pipeline to the `Provider` contract, rather than adding a RAG-specific evaluation path

`app/rag/provider_adapter.py`'s `RAGProvider` implements the same `Provider` protocol (`name`, `model`, `generate(request) -> response`) as `DeterministicProvider`/`OpenAIProvider`/`GeminiProvider`. It wraps a `Retriever` and a generation `Provider` internally, but from `EvaluationRunner`'s point of view it's just another `Provider` — `POST /rag/evaluate/{case_id}` calls `EvaluationRunner.evaluate_case` (made public this sprint; it was previously a private helper only `run_with_ provider` called internally) exactly the way a plain-provider case would be graded.

### 19. Golden dataset extended in place (v1.1.0), with fixtures covering every case — not a separate RAG-only dataset

The 18 new RAG cases live in the *same* `customer_support_bot` dataset, as v1.1.0 (`customer_support_bot.v1.1.0.json`), alongside the original 22 v1.0.0 cases — not a new `customer_support_bot_rag` dataset. `customer_support_bot.v1.1.0.fixtures.json` has a canned response for all 40 cases, including the 18 new ones, so `POST /evaluations/runs` (Sprint 3's bulk endpoint, provider defaulting to `"deterministic"`) grades the whole v1.1.0 dataset — RAG cases included — exactly the way it always has, with no RAG-specific code path.

### 20. ChromaDB persists to disk with idempotent, hash-checked re-ingestion

`ChromaVectorStore` (`app/rag/vector_store.py`) persists to `backend/chroma_store/` (gitignored) via `langchain_chroma.Chroma`'s `persist_directory`. `RAGCorpusService.ingest_if_needed()` (`app/rag/corpus_service.py`) computes a hash of the loaded+chunked corpus and compares it against a hash recorded in a plain marker file (`chroma_store/.corpus_hash`) the last time ingestion ran; it only wipes and re-embeds the collection when the hash differs, mirroring `DatasetService.load_all()`'s "files on disk are the source of truth, reloaded at every startup" pattern from [[Sprint 2 decision 11]] — but without paying the (here, non-trivial for a real embedding model) re-embedding cost on every restart when nothing changed.

## Sprint 5 — RAGAS Integration

### 21. Zero changes to `EvaluationRunner`; RAGAS evaluators are added by changing evaluator construction in `main.py`

Before writing any Sprint 5 code, we inspected `app/evaluation/base.py` and `app/evaluation/runner.py` to find the smallest clean extension for a framework-backed evaluator. `EvaluationRunner.__init__` already accepts an injected `evaluators: list[Evaluator] | None` and `evaluate_case` already applies whichever evaluators are present via `applies_to`/`evaluate` — nothing in the runner assumes "deterministic" or hardcodes `DEFAULT_EVALUATORS`. So Sprint 5 adds 4 new `Evaluator` implementations (`app/evaluation/ragas/evaluator.py`) and changes exactly one line's worth of wiring in `create_app()` (`app/main.py`): `evaluators = list(DEFAULT_EVALUATORS) + build_ragas_evaluators(settings)`, passed into `EvaluationRunner(evaluators=evaluators)`. `runner.py` itself is byte-for-byte unchanged from Sprint 4.

### 22. RAGAS-specific types are confined to `RagasClient`; its failures reuse `ProviderErrorType`, not a new enum

`app/evaluation/ragas/client.py` is the only module in the codebase that imports `ragas` or constructs the `openai.OpenAI` client used purely as RAGAS's LLM judge/embeddings backend (via `ragas.llms.llm_factory` and `ragas.embeddings.base.embedding_factory`, RAGAS's modern `ragas.metrics.collections` API). `app/evaluation/ragas/evaluator.py` never imports `ragas` — it only ever receives a `RagasScore` (success) or catches a `RagasEvaluatorError` (infrastructure failure) from `RagasClient`. `RagasEvaluatorError.error_type` reuses the **existing** `app.providers.types.ProviderErrorType` enum (`TIMEOUT`/`AUTHENTICATION`/ `RATE_LIMIT`/`UNAVAILABLE`/`MALFORMED_RESPONSE`) rather than introducing a second, RAGAS-specific error-type enum.

## Sprint 6 — DeepEval Integration

### 23. Only one DeepEval metric ships this sprint: G-Eval custom criteria; answer relevancy, faithfulness, and hallucination are omitted as duplicates of Sprint 5's RAGAS metrics

Before implementing anything, we compared each of the sprint brief's 4 "potential areas" against what Sprint 5's RAGAS evaluators and Sprint 1-4's deterministic evaluators already cover:

### 24. `DeepEvalCriteriaEvaluator` is opt-in per case via `case.metadata`; `DeepEvalClient` isolates `deepeval` exactly like `RagasClient` isolates `ragas`

`DeepEvalCriteriaEvaluator.applies_to(case)` returns `bool(case.metadata.get("deepeval_criteria"))` — a case with no criteria string is simply not applicable, the same data-driven pattern `CitationPresenceEvaluator` (Sprint 2) and RAGAS's `_is_rag_case` (Sprint 5) both use. The criteria string itself, and two optional per-case overrides (`deepeval_criteria_name` for the metric label, `deepeval_threshold` for a per-case pass/fail cutoff), all live in `case.metadata` — Quality-Gate-owned dataset data, never DeepEval's — satisfying "thresholds owned by Quality Gate configuration" even when a threshold varies per case rather than being one fixed `Settings` value.

### 25. Evaluator-combination selection is a `frameworks` field on the existing run/evaluate endpoints, backed by a `framework` attribute added to the `Evaluator` protocol — no new CLI, no new runner

`Evaluator` (`app/evaluation/base.py`) gained a `framework: str` attribute alongside `name: str`. Every existing evaluator — all 8 deterministic, all 4 RAGAS, the 1 DeepEval — now exposes it as a class attribute. `EvaluationRunner.run`/`run_with_provider`/`evaluate_case` all gained an optional `frameworks: set[str] | None` keyword parameter; when given, evaluation filters `self._evaluators` down to `e.framework in frameworks` before applying `applies_to`/`evaluate`. `POST /evaluations/runs` and `POST /rag/evaluate/{case_id}` both gained an optional `frameworks` request field threading straight through `EvaluationService.run`/`RAGService.evaluate_case` to the runner. `None` (the default, and what every Sprint 1-5 caller/test still passes implicitly) runs every evaluator the runner was constructed with — byte-identical to pre-Sprint-6 behavior.

## Sprint 7 — OpenAI Evals Integration

### 26. The hosted `/v1/evals` API is deliberately never called; "OpenAI Evals Integration" is built as direct, Structured-Outputs-backed grading calls through the Responses API instead

Before writing any code, we checked OpenAI's current documentation for the Evals platform, per the sprint's own instruction to "inspect current supported OpenAI evaluation patterns" and "avoid deprecated APIs unless explicitly documented." We found that OpenAI announced on 2026-06-03 that the entire Evals platform — the `/v1/evals` API, its graders (`string_check`, `text_similarity`, model/label graders), and the dashboard — is being deprecated: read-only for existing users on 2026-10-31, full shutdown on 2026-11-30. This was surfaced to the user before implementation (rather than silently built around), and two paths were offered: build the adapter against the still-functional-but-sunsetting `/v1/evals` API anyway, or skip it entirely and reimplement the useful *grading concepts* as direct model calls. The user chose the latter.

### 27. Two OpenAI-model-graded evaluators cover four requested task areas; no answer-relevancy/faithfulness/hallucination duplicate is added a third time

The sprint asked for coverage of four regression-task areas: structured answer correctness, policy compliance, expected-behavior classification, and engineering-domain quality cases. Rather than build four separate evaluators, each area was compared against what already exists (RAGAS's Sprint 5 metrics, DeepEval's G-Eval from Sprint 6, and the deterministic evaluators) and grouped by the *shape* of judgment each actually needs:

## Sprint 8 — Release Policy Engine and Regression Baselines

### 28. Some policy checks are hard-BLOCK-only; others are policy-configurable BLOCK/WARN/ignore — the split follows "is this a quality question or an operational one"

`PolicyEngine` treats two kinds of failure as always a hard BLOCK, with no policy-level way to downgrade them: - the overall case pass rate falling below `ReleasePolicy.min_pass_rate`, - a *required* metric's aggregate score falling below its own   `RequiredMetricPolicy.min_score`.

### 29. Policies, baselines, and gate decisions persist to SQLite as JSON blobs behind the existing `Repository[T]` shape; datasets/runs/case-results remain in-memory

`app/repositories/sqlite.py`'s `SQLiteRepository[T]` implements the exact same five-method contract (`add`/`get`/`list`/`delete`/`count`) that `InMemoryRepository[T]` (Sprint 1) already established, so it is a drop-in swap for any consumer written against that shape — no new repository *interface* was introduced. Each item is stored as a single JSON blob (`item.model_dump_json()`) in a two-column table (`id TEXT PRIMARY KEY, data TEXT`), rather than a normalized relational schema with one column per field. `PolicyRepository`, `BaselineRepository`, and `GateDecisionRepository` subclass it and add a small number of purpose-built query methods (`get_active`, `get_latest_for_dataset`, `list_for_run`, `list_history`) that filter/sort the full `list()` result in Python rather than via SQL `WHERE`/`ORDER BY`. One connection is opened per repository instance and held open for its whole...

## Sprint 9 — Arize Phoenix Observability

### 30. Tracing is OpenTelemetry-native with dependency-injected `Tracer`s, never global OTel state; Phoenix is a separate process this app only ever talks to over the network

`app/observability/tracing.py`'s `configure_tracing()` is the entire integration surface. It returns a plain `opentelemetry.trace.Tracer` — never a Phoenix-specific type, never anything evaluation/RAG code has to know is Phoenix-flavored. When `AQG_TRACING_ENABLED=true`, it attempts `phoenix.otel.register(..., set_global_tracer_provider=False)` and returns `provider.get_tracer(...)`; on ANY exception, or when tracing is disabled, it returns OpenTelemetry's own built-in tracer (`trace.get_tracer(...)` with no provider ever registered), which is a genuine no-op implementation built into the OTel API itself, not something this codebase built. The returned `Tracer` — real or no-op — is threaded into `EvaluationRunner` and `Retriever` (via `build_retriever`) by ordinary constructor injection, the same pattern `Provider`/`Evaluator` implementations already use; it is never installed as...

### 31. Reports are a pure presentation layer computed on demand, never persisted, never a second source of truth

`app/reports/report.py`'s `build_report()` takes a `GateDecision` + its `EvaluationRun` + `CaseResult`s (all already fetched via `PolicyService`, which the sprint's `ReportService` composes over rather than duplicates) and assembles a `Report` — the same data, denormalized into one shape, plus a handful of cheap run-wide aggregates (pass rate, mean latency, total cost/tokens) that are trivial to derive from `case_results` and would otherwise be recomputed by every caller that wants them. Nothing about `Report` is stored anywhere: there is no `ReportRepository`, no SQLite table, no `report_id`. `GET /reports/{decision_id}/json` and `/html` compute a fresh `Report` on every request. `app/reports/html.py` renders the same `Report` as one self-contained HTML page using plain f-strings and `html.escape` — no Jinja2 or other template-engine dependency, matching the "isolated,...

### 32. The dashboard is a thin, read-mostly client with zero business logic of its own

`frontend/` is a Vite + React + TypeScript single-page app that talks exclusively to the existing HTTP API (`src/api/client.ts`) — it computes nothing the backend doesn't already return, stores no state beyond what's needed to render the current page (a small `useApiData` hook wrapping loading/error/data, no Redux/Zustand/React Query), and owns no domain logic: a decision's PASS/WARN/BLOCK color, a run's pass rate, a policy's required metrics are all values the API already computed and the dashboard only displays. The one exception — the "Run gate" button in Run Detail — still just calls `POST /gate/decisions` and renders whatever `GateDecision` comes back; it does not evaluate anything client-side. All five views are read-oriented; the dashboard has no create/edit forms for policies or baselines this sprint (registering a policy or approving a baseline still goes through the API...

### 33. The frontend Docker image resolves its API URL at container start, not build time — one image, many deployments

`frontend/docker-entrypoint.sh` runs before nginx starts and writes `/usr/share/nginx/html/env-config.js` from the container's `API_BASE_URL` environment variable, setting `window.__APP_CONFIG__ = { API_BASE_URL: "..." }`. `index.html` loads this via a plain `<script>` tag before `src/main.tsx`, and `src/api/client.ts`'s `API_BASE_URL` resolves in this order: `window.__APP_CONFIG__.API_BASE_URL` (Docker, runtime) → `import.meta.env.VITE_API_BASE_URL` (Vite's own build-time env, for local `npm run dev`/`npm run build`) → a hardcoded `http://localhost:8000/api/v1` default. A committed stub (`frontend/public/env-config.js`, `window.__APP_CONFIG__ = {}`) means `index.html`'s script tag never 404s outside Docker; the entrypoint overwrites that file fresh on every container start.

### 34. `scripts/smoke_test.sh` is the single source of truth for "is a running instance actually healthy," reused by both the plain-process and Docker-image CI jobs

`scripts/smoke_test.sh` takes one argument (a base URL) and exercises the real, running HTTP API end to end: `GET /health` → `POST /evaluations/runs` (deterministic provider) → `GET /evaluations/runs` (confirm the new run is listed) → `POST /gate/decisions` → `GET /reports/{id}/json` and `/html` (confirm both parse/look right). It makes no assumption about *how* the server at that URL was started — a bare `uv run uvicorn`, a `docker run` container, anything else that speaks HTTP on that port. `.github/workflows/pr.yml`'s "smoke-suite" job runs it against a plain `uv run` process; the "docker-build" job runs the exact same script, unmodified, against the actual built backend container.

### 35. Evaluator failure isolation reuses the existing infrastructure-error convention instead of inventing a parallel one; "partial" is one signal covering both

When `EvaluationRunner` catches an evaluator timing out or raising an unexpected exception, it converts that into an ordinary `MetricResult` with `metadata["error_type"]` set to `"timeout"` or `"unavailable"` (`_isolated_failure_result`) — the exact same convention Sprint 5/6/7's RAGAS/DeepEval/OpenAI-Evals clients already use for their own judge-call infrastructure failures (a rate limit, an auth error, a malformed judge response). `app/policy/engine.py`'s `_metric_status()` already classifies any `MetricResult` with `metadata["error_type"]` as `infrastructure_error`, so no changes were needed there at all. `CaseResult.partial` is `True` whenever *any* metric result in that case carries `error_type` — whether it came from a framework's own client hitting a normal infrastructure failure, or from this sprint's new runner-level isolation. Both facts mean the same thing from a caller's...

### 36. Request size limiting checks Content-Length only; closing the chunked-transfer gap was judged lower-value than shipping the common-case protection now

`MaxBodySizeMiddleware` rejects a request with 413 when its `Content-Length` header declares a size over `AQG_MAX_REQUEST_BODY_BYTES` — checked before any handler reads the body, with zero buffering. It does not stream and count bytes as they arrive, so a client that omits `Content-Length` via chunked transfer encoding could still send an oversized body past this check.

### 37. A single shared API key gating write access is "basic RBAC," not a placeholder — full per-user RBAC was explicitly out of scope, not merely deferred by accident

`app/core/auth.py` ships exactly two roles: anyone (no credential needed) can read, and the holder of one shared secret (`AQG_API_KEY`) can write. There is no per-user identity, no distinction between "can run evaluations" and "can register a new policy," and no audit trail of *which* key-holder did *what* beyond whatever the request logs already capture (Sprint 12 also added: every gate decision and evaluation run completion is logged with full context, just not a specific human identity). The `AuthBackend` Protocol exists specifically so a real system (per-user keys mapped to permissions, JWT- based identity, a roles table) can be dropped in behind `require_write_access` later without touching a single router — every gated endpoint depends on `require_write_access`, never on `ApiKeyAuthBackend` directly.

### 38. Evaluator timeouts stop the caller from waiting, not the evaluator from running — Python's threading model makes a true hard-kill unavailable without a much larger change

`EvaluationRunner._call_evaluator` runs `Evaluator.evaluate()` in a single-worker `ThreadPoolExecutor` and calls `future.result(timeout=...)`. On a timeout, the executor is shut down with `wait=False, cancel_futures=True` — meaning the *caller* stops waiting and moves on immediately, but the already-running worker thread is not forcibly terminated; it keeps executing in the background (invisibly, with its eventual result discarded) until it finishes or the process itself exits.
