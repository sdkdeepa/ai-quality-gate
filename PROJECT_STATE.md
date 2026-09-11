# PROJECT_STATE

Last updated: 2026-09-10 (Sprint 5 complete)

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
    │   ├── customer_support_bot.v1.0.0.json             # 22-case seed golden dataset
    │   ├── customer_support_bot.v1.0.0.fixtures.json    # deterministic fixture responses
    │   ├── customer_support_bot.v1.1.0.json             # v1.0.0's 22 cases + 18 RAG cases (Sprint 4)
    │   └── customer_support_bot.v1.1.0.fixtures.json    # fixtures for all 40 v1.1.0 cases
    ├── rag_corpus/             # small knowledge base (data, not code) — see RAG system below
    │   └── *.md                 # 9 short policy documents (returns, warranty, shipping, ...)
    ├── chroma_store/           # gitignored; persisted ChromaDB, rebuilt from rag_corpus/ on startup
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
        ├── evaluation/          # the internal evaluation interface + deterministic/RAGAS plugins
        │   ├── base.py              # Evaluator protocol (applies_to + evaluate -> MetricResult)
        │   ├── types.py             # EvaluationInput, FixtureResponse
        │   ├── deterministic.py     # 8 deterministic evaluators + DEFAULT_EVALUATORS
        │   ├── runner.py            # EvaluationRunner: dataset + provider -> EvaluationRun + CaseResults
        │   └── ragas/               # Sprint 5 — RAGAS integration, isolated behind the same Evaluator protocol
        │       ├── client.py            # RagasClient: only module importing `ragas`/building its judge client
        │       ├── evaluator.py         # RagasFaithfulness/AnswerRelevancy/ContextPrecision/ContextRecallEvaluator
        │       └── factory.py           # build_ragas_evaluators(settings) -> list[Evaluator], config-gated
        ├── providers/           # the internal provider interface + provider implementations
        │   ├── types.py             # ProviderRequest, ProviderResponse, ProviderError(Type)
        │   ├── base.py              # Provider protocol (name, model, generate)
        │   ├── cost.py              # CostCalculator protocol + TableCostCalculator + pricing tables
        │   ├── deterministic.py     # DeterministicProvider (wraps fixtures as a Provider)
        │   ├── openai_provider.py   # OpenAIProvider (only module importing `openai`)
        │   ├── gemini_provider.py   # GeminiProvider (only module importing `google.genai`)
        │   └── factory.py           # ProviderFactory: name -> Provider, resolves Settings/API keys
        ├── rag/                 # sample RAG system-under-test (Sprint 4) — NOT part of the Gate
        │   ├── types.py             # RetrievedChunk, RAGAnswer
        │   ├── loader.py            # rag_corpus/*.md -> LangChain Document (our own code)
        │   ├── chunking.py          # Document -> chunks via LangChain RecursiveCharacterTextSplitter
        │   ├── embeddings.py        # Embeddings abstraction: DeterministicEmbeddings, OpenAIEmbeddings
        │   ├── vector_store.py      # ChromaVectorStore: langchain_chroma.Chroma + persistence/idempotency
        │   ├── corpus_service.py    # RAGCorpusService.ingest_if_needed() (idempotent, hash-checked)
        │   ├── retriever.py         # Retriever: query -> relevance-filtered RetrievedChunks (our own code)
        │   ├── prompt.py            # build_prompt(query, chunks) -> str (our own code)
        │   ├── pipeline.py          # RAGPipeline: query -> retrieve -> prompt -> Provider -> RAGAnswer
        │   ├── provider_adapter.py  # RAGProvider(Provider): makes the pipeline itself a Provider
        │   └── factory.py           # build_retriever(settings): wires embeddings/store/ingestion
        ├── repositories/       # storage abstraction
        │   ├── base.py             # Repository protocol
        │   └── in_memory.py        # InMemoryRepository[T], InMemoryCaseResultStore
        ├── services/           # application/orchestration layer
        │   ├── status_service.py     # assembles /api/v1/status payload
        │   ├── dataset_service.py    # load/validate/list/get datasets + fixtures from disk
        │   ├── evaluation_service.py # orchestrates dataset -> provider factory -> runner -> repositories
        │   └── rag_service.py        # orchestrates RAG query / chunk inspection / evaluate-a-case
        ├── api/                 # HTTP layer (FastAPI routers)
        │   ├── deps.py              # FastAPI dependency providers
        │   ├── _view.py             # metrics_by_framework(): groups a CaseResult's MetricResults by framework
        │   ├── health.py            # GET /health
        │   ├── status.py            # GET /api/v1/status
        │   ├── datasets.py          # GET /api/v1/datasets, GET /api/v1/datasets/{name}/{version}
        │   ├── evaluations.py       # POST /api/v1/evaluations/runs, GET /api/v1/evaluations/runs/{id}
        │   └── rag.py                # POST /rag/query, GET /rag/chunks, POST /rag/evaluate/{case_id}
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

**Plugin boundary (now proven twice over):** `app/evaluation/base.py`
defines the `Evaluator` protocol — `applies_to(case)` + `evaluate(input) ->
MetricResult`. The 8 deterministic evaluators in `app/evaluation/deterministic.py`
were the first implementation of that protocol; the 4 RAGAS evaluators in
`app/evaluation/ragas/evaluator.py` (Sprint 5) are the second, and neither
`EvaluationRunner` nor the `Evaluator` protocol itself changed to add them —
see Sprint 5's decision below. They know nothing about HTTP, datasets-on-disk,
or release policy — they take an `EvaluationInput` and return a normalized
`MetricResult`. `EvaluationRunner` composes evaluators against a dataset's
cases; it does **not** compute a PASS/WARN/BLOCK decision — that remains
future work for the Gate's policy layer. When DeepEval/OpenAI Evals/Phoenix
are integrated in a later sprint, they will implement this same `Evaluator`
protocol side-by-side with the deterministic and RAGAS ones.

**RAGAS is an evaluation signal provider, not a policy owner (Sprint 5):**
`app/evaluation/ragas/` adapts RAGAS's `Faithfulness`/`AnswerRelevancy`/
`ContextPrecision`/`ContextRecall` metrics behind the same `Evaluator`
protocol as everything else. RAGAS-specific types (`ragas.metrics.collections.*`,
`ragas.llms.*`, `ragas.embeddings.*`) are confined to `app/evaluation/ragas/client.py`
— the only module that imports `ragas` or builds the OpenAI client used
purely as RAGAS's LLM judge — exactly like `openai_provider.py`/`gemini_provider.py`
are the only modules importing their respective SDKs. The rest of the app
only ever sees normalized `MetricResult`s with `framework="ragas"`; RAGAS
never computes a PASS/WARN/BLOCK decision, and thresholds
(`AQG_RAGAS_*_THRESHOLD`) live in the Gate's own `Settings`, not inside
RAGAS. See [[Sprint 5 decision 21]] and [[Sprint 5 decision 22]].

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

**The RAG system is a system under test, not part of the Quality Gate
(Sprint 4):** `app/rag/` builds a small, real retrieve-then-generate
pipeline (LangChain document loading/chunking + ChromaDB + a Sprint 3
`Provider` for generation) — but it exists solely so the Gate has something
realistic to evaluate. The Gate's evaluation logic (`app/evaluation/`) never
imports anything from `app/rag/`; the dependency runs one way, RAG ->
providers, exactly like every other system-under-test path. The only place
`app/rag` and `app/evaluation` meet is `RAGProvider`
(`app/rag/provider_adapter.py`), which makes the RAG pipeline *look like* a
plain `Provider` so `EvaluationRunner.evaluate_case` can grade a RAG case
with the same 8 deterministic evaluators as everything else — no
RAG-specific evaluator, no RAG-specific branch in the runner. See
[[Sprint 4 decision 17]] for exactly where LangChain is used vs. our own code.

## Completed capabilities (Sprint 1 + Sprint 2 + Sprint 3 + Sprint 4 + Sprint 5)

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

**Sprint 4 — Sample RAG System using LangChain and ChromaDB:**
- Small local knowledge corpus (`backend/rag_corpus/*.md`, 9 short policy
  documents): return policy (30-day standard / 45-day defective), warranty
  (1-year electronics / 2-year appliances), shipping (current $4.99/$14.99
  policy **plus** a deliberately superseded 2023 archive doc at $6.99/$17.99
  — an intentional in-corpus conflict), loyalty program, data retention,
  account security, subscription management, support hours.
- Ingestion (`app/rag/loader.py` + `chunking.py` + `embeddings.py` +
  `vector_store.py` + `corpus_service.py`): load `.md` files -> LangChain
  `Document`s with `source_id`/`title` metadata (our own code) ->
  `RecursiveCharacterTextSplitter` chunks stamped with a stable
  `{source_id}::chunk-{n}` `chunk_id` (LangChain) -> embedded ->
  `langchain_chroma.Chroma`, persisted to `backend/chroma_store/`
  (gitignored). Idempotent: `RAGCorpusService.ingest_if_needed()` hashes the
  chunk set and skips re-embedding if the corpus is unchanged since the last
  ingest — mirrors `DatasetService.load_all()`'s "source of truth on disk,
  rebuilt at startup" pattern from Sprint 2.
- Embeddings abstraction (`app/rag/embeddings.py`): a `langchain_core`
  `Embeddings` subclass either way. `DeterministicEmbeddings` (default) is
  an offline hashing-trick bag-of-words embedder — deterministic, no API
  key, mirrors `DeterministicProvider`'s role in keeping ingestion/tests/CI
  fully offline. `OpenAIEmbeddings` is a thin wrapper around the OpenAI
  embeddings endpoint (opt-in via `AQG_RAG_EMBEDDINGS_PROVIDER=openai` +
  `AQG_OPENAI_API_KEY`).
- Retrieval (`app/rag/retriever.py`, our own code — not a LangChain
  `Retriever`): query -> `ChromaVectorStore.similarity_search` -> chunks
  with `text`, `source_id`, `chunk_id`, and `relevance_score` (cosine
  similarity, converted from Chroma's returned distance). A relevance floor
  (`DEFAULT_RELEVANCE_THRESHOLD = 0.08`, tuned empirically against this
  corpus) drops chunks below it — without it Chroma always returns `k`
  results regardless of relevance, so a genuinely off-topic query would
  never be distinguishable from a weak match.
- RAG pipeline (`app/rag/pipeline.py`): `RAGPipeline.answer(query)` = query
  -> `Retriever.retrieve` -> `build_prompt` (`app/rag/prompt.py`, our own
  code — plain string templating, not a LangChain `PromptTemplate`) -> a
  Sprint 3 `Provider.generate()` -> `RAGAnswer` (query, answer, retrieved
  chunks, provider, model, retrieval/generation/total latency, tokens,
  estimated cost, normalized error). The generation step is any `Provider`
  — `DeterministicProvider`, `OpenAIProvider`, or `GeminiProvider` — so
  swapping fixture-backed generation for a live model is a config choice.
- `RAGProvider` (`app/rag/provider_adapter.py`): adapts `RAGPipeline` to the
  `Provider` contract itself, so `EvaluationRunner.evaluate_case` (Sprint 3's
  method, made public this sprint) can grade a RAG case exactly like any
  other case — real retrieval feeds `ProviderResponse.retrieved_context`,
  which is what makes `CitationPresenceEvaluator` meaningful for RAG cases.
- Golden dataset extended: `customer_support_bot` v1.1.0
  (`backend/datasets/customer_support_bot.v1.1.0.json` +
  `.fixtures.json`) = the original 22 v1.0.0 cases + **18 new
  category=`"rag"` cases** spanning all 7 required scenarios (`metadata.
  rag_scenario`): correct (4), partial (3), irrelevant (2), missing (3),
  conflicting (2), unsupported (2), multi-chunk (2). 4 of the 18 are
  `critical=true`. Fixtures are crafted so the v1.1.0 run has **31
  passing / 9 failing** (the original 7 plus 2 new deliberate RAG
  failures) and **3 critical failures** (`str-002`, `neg-001` from
  v1.0.0, plus `rag-013`) — the conflicting-shipping-cost case, whose
  fixture deliberately cites the superseded $6.99 figure to prove
  `forbidden_phrases` catches picking the wrong source when two chunks
  disagree; `rag-009` deliberately answers an off-topic question
  confidently instead of refusing, to prove `expected_refusal` still
  catches that failure mode for RAG-sourced (not just canned) answers.
  Verified empirically that live retrieval against the real corpus
  behaves as each scenario intends (irrelevant/unsupported -> 0 chunks;
  missing -> on-topic chunk retrieved despite the fact being absent;
  conflicting -> both shipping docs retrieved; multi-chunk -> both needed
  sources retrieved) — see `tests/rag/test_unsupported_queries.py` and
  `tests/api/test_rag_api.py`.
- `RAGService` (`app/services/rag_service.py`) + 3 new API endpoints
  (`app/api/rag.py`, mounted under `/api/v1/rag`):
  - `POST /rag/query` — ad-hoc query through the real pipeline; a manual
    debugging/exploration tool for the system under test, not a chat
    endpoint, and nothing else in the Gate depends on it. `provider` is
    required and restricted to `"openai"|"gemini"` (no `"deterministic"`
    default) — an ad-hoc query has no case_id for
    `DeterministicProvider` to look a canned answer up by.
  - `GET /rag/chunks` — inspect the corpus: lists every ingested chunk, or
    (with `?query=`) previews what retrieval would return, ranked with
    relevance scores, without running generation.
  - `POST /rag/evaluate/{case_id}` — runs one RAG dataset case through
    real retrieval + the selected generation provider (default
    `"deterministic"`, no API key needed) and grades it with the same
    deterministic evaluators as the rest of the Gate; returns the
    `CaseResult` plus the retrieved chunks (with scores) for debugging.
    Distinct from `POST /evaluations/runs`, which runs a whole dataset
    without any RAG-specific detail in the response.
- New settings (`AQG_` prefix): `RAG_CORPUS_DIR` (default `rag_corpus`),
  `RAG_CHROMA_DIR` (default `chroma_store`), `RAG_COLLECTION_NAME`
  (default `rag-corpus`), `RAG_EMBEDDINGS_PROVIDER` (default
  `deterministic`), `RAG_TOP_K` (default `4`), `RAG_RELEVANCE_THRESHOLD`
  (default `0.08`), `RAG_DATASET_NAME` (default `customer_support_bot`).
- 96 new tests (271 total): ingestion (loader, chunking, corpus-service
  idempotency), vector store (persistence, hash-based re-ingest
  detection), embeddings (determinism, dimension, stopword filtering;
  mocked `OpenAIEmbeddings`), retriever (relevance filtering, ranking),
  pipeline (via a fake `Provider` — no real SDK or network), `RAGProvider`
  contract tests, `RAGService`, the 3 new API endpoints, and a dedicated
  `test_unsupported_queries.py` exercising the real corpus end-to-end for
  every irrelevant/missing/unsupported case. Also updated 2 pre-existing
  tests that hardcoded `"latest" -> "1.0.0"` now that v1.1.0 exists.
- Explicitly out of scope per the sprint plan (deferred, not attempted):
  RAGAS, DeepEval, OpenAI Evals, Phoenix.

**Sprint 5 — RAGAS Integration:**
- `app/evaluation/ragas/` adds RAG-focused evaluation signal through an
  adapter, without coupling the Gate's release policy to RAGAS. Zero
  changes to `EvaluationRunner` or the `Evaluator` protocol — the smallest
  clean extension was to build new `Evaluator` implementations and change
  only how `EvaluationRunner` is *constructed* in `main.py`
  (`DEFAULT_EVALUATORS + build_ragas_evaluators(settings)`). See
  [[Sprint 5 decision 21]].
- `RagasClient` (`app/evaluation/ragas/client.py`) is the only module
  importing `ragas` or building the OpenAI client used purely as RAGAS's
  LLM judge/embeddings (`ragas.llms.llm_factory` +
  `ragas.embeddings.base.embedding_factory`, both from `ragas.metrics.collections`'s
  modern API) — mirrors `openai_provider.py`/`gemini_provider.py` being the
  only modules importing their SDKs. Every SDK/RAGAS exception it can raise
  is caught and mapped onto the **existing** `ProviderErrorType` vocabulary
  (`timeout`/`authentication`/`rate_limit`/`unavailable`/`malformed_response`)
  via `RagasEvaluatorError` — no second error-type enum. See
  [[Sprint 5 decision 22]].
- 4 evaluators in `app/evaluation/ragas/evaluator.py`, all
  `framework="ragas"`: `RagasFaithfulnessEvaluator` (needs retrieved
  context + a response; no reference answer), `RagasAnswerRelevancyEvaluator`
  (needs only a response — still runs for refusal/unsupported RAG cases),
  `RagasContextPrecisionEvaluator` and `RagasContextRecallEvaluator` (both
  need `case.expected_answer` as the reference **and** retrieved context —
  the irrelevant/missing/unsupported RAG scenarios have neither by design,
  so these two are explicitly **skipped**, not scored, for 9 of the 18
  v1.1.0 RAG cases). `applies_to` is data-driven off `_is_rag_case`
  (category `"rag"`, a populated `reference_context`, or `rag_scenario`
  metadata) — same pattern as `CitationPresenceEvaluator`.
- **Three normalized non-quality states**, all carried in
  `MetricResult.metadata["ragas_status"]` (no domain model changes needed —
  `metadata: dict[str, Any]` already existed for exactly this):
  `"scored"` (a real RAGAS judgment against `threshold`), `"skipped_missing_input"`
  (case lacks a required input; `passed=True` — not-applicable must not fail
  a case) and `"infrastructure_error"` (RAGAS/its dependencies/the judge
  model failed to execute; `passed=False` so an outage never silently
  produces PASS, but `explanation`/`metadata["error_type"]` make clear this
  is **not** a quality score of 0 — a future Policy Engine sprint can treat
  it differently, e.g. WARN, from a real threshold miss).
- Configuration (`AQG_RAGAS_*`, all in `Settings`): `ragas_enabled` (default
  `false` — zero import/behavior impact on the rest of the Gate when
  unset), `ragas_metrics` (comma-separated subset of the 4 metric names),
  `ragas_llm_model` (falls back to `AQG_OPENAI_MODEL`), `ragas_embedding_model`,
  and one threshold setting per metric. `build_ragas_evaluators` (`app/evaluation/ragas/factory.py`)
  fails fast at app-startup (`RagasConfigurationError`, a plain `RuntimeError`
  — no HTTP request exists yet to attach an `AppError` response to) if
  `ragas_enabled=true` without `AQG_OPENAI_API_KEY`, or if `ragas_metrics`
  names something outside the known 4. Gemini-backed RAGAS judging is
  **not implemented** this sprint (see Outstanding work below).
- Comparison output (requirement #8): `app/api/_view.py`'s
  `metrics_by_framework()` groups a `CaseResult`'s `MetricResult`s by
  `framework`. Wired additively into `GET /api/v1/evaluations/runs/{id}`
  (new `metrics_by_framework: {case_id: {framework: [MetricResult]}}` key)
  and `POST /rag/evaluate/{case_id}` (new `metrics_by_framework: {framework:
  [MetricResult]}` key) — existing response shapes unchanged, no frontend.
- Dependency pin discovered and fixed: `ragas==0.4.3` imports
  `langchain_community.chat_models.vertexai`, which moved to the
  `langchain_classic` package in `langchain-community>=0.4.0` — that
  combination fails at import time. Pinned `langchain-community>=0.3.31,<0.4.0`,
  `langchain-core>=0.3.0,<1.0.0`, `langchain-openai>=0.3.0,<0.4.0` in
  `pyproject.toml`; verified these resolve and import cleanly via `uv sync`.
- 53 new tests (324 total, 2 still self-skipped without live API keys):
  `RagasClient` exception-mapping/value-parsing (mocked — no `ragas`/`openai`
  network calls), all 4 evaluators' `applies_to`/skip/infrastructure-failure/
  pass/fail paths, `build_ragas_evaluators` config-error and
  selected-metrics-configuration paths, `EvaluationRunner` producing both
  deterministic and RAGAS `MetricResult`s for the same RAG case (with a
  fake `Evaluator` standing in for the real RAGAS ones — no ragas import in
  that test), `create_app()`'s evaluator-count wiring for
  enabled/disabled/selected-metrics/missing-key, and the two new API
  `metrics_by_framework` fields. All mocked by default — no RAGAS/OpenAI
  API calls or charges from the normal test suite.
- Explicitly out of scope per the sprint plan (deferred, not attempted):
  DeepEval, OpenAI Evals, Phoenix, the PASS/WARN/BLOCK policy engine, a
  regression baseline engine, JSON/HTML report generation, Docker/CI changes.

## Current sprint

Sprint 5 — RAGAS Integration: **complete**.

## Outstanding work (future sprints, not started)

- **RAGAS real-provider validation**: every RAGAS test in the suite mocks
  the OpenAI SDK boundary — no test has yet run a real RAGAS judge call
  against a live OpenAI API key. Deferred, same shape as the Sprint 3
  OpenAI/Gemini smoke-test gap below; not a blocker (see MANUAL VALIDATION
  in the Sprint 5 PR/commit for exact steps once a key is available).
- **Gemini-backed RAGAS judging**: `RagasClient` only builds its LLM judge
  via `ragas.llms.llm_factory(..., client=openai.OpenAI(...))`; RAGAS's
  `litellm` adapter would be needed to back the judge with Gemini instead.
  Not implemented this sprint — `AQG_RAGAS_ENABLED=true` always requires
  `AQG_OPENAI_API_KEY`, independent of which provider generates the answer
  being graded.
- **RAGAS results feeding the Policy Engine**: `MetricResult.metadata["ragas_status"]`
  (`scored`/`skipped_missing_input`/`infrastructure_error`) exists
  specifically so a future Policy Engine sprint can treat an infrastructure
  failure differently (e.g. WARN/retry) from a real threshold miss (BLOCK)
  — nothing consumes that distinction yet, since `GateDecision` computation
  doesn't exist yet at all (see the pre-existing Sprint 4 outstanding item
  below).


- Real-provider smoke validation: run `uv run pytest -v -m smoke` (or a
  live `"provider": "openai"`/`"gemini"` API call) with
  `AQG_OPENAI_API_KEY`/`AQG_GEMINI_API_KEY` set — deferred at the end of
  Sprint 3, still not done. Not a blocker.
- Live-provider RAG validation: `POST /rag/query` and `POST
  /rag/evaluate/{case_id}` with `provider="openai"`/`"gemini"` — the RAG
  pipeline has only been exercised against `DeterministicProvider` so far
  (real retrieval, canned generation); a real generation call through the
  RAG pipeline hasn't been manually validated yet.
- Framework-backed evaluators (DeepEval, OpenAI Evals) implementing the
  same `Evaluator` protocol as the deterministic and RAGAS ones. RAGAS
  itself shipped in Sprint 5; DeepEval/OpenAI Evals remain the natural next
  signals to add behind the same protocol.
- Real embeddings in practice: `OpenAIEmbeddings` exists and is wired
  through `AQG_RAG_EMBEDDINGS_PROVIDER=openai`, but hasn't been run
  against the corpus — `DeterministicEmbeddings` is the only embeddings
  backend exercised by tests/CI so far.
- Retrieval quality metrics (precision@k, recall@k, MRR against
  `reference_context`) — Sprint 4 only proves chunks are retrieved/
  filtered correctly per scenario (see `test_unsupported_queries.py`),
  it doesn't score retrieval quality numerically.
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

Sprint 4's RAG endpoints (system-under-test, not the Gate itself):

```bash
# inspect the full ingested corpus
curl http://127.0.0.1:8000/api/v1/rag/chunks

# preview what retrieval would return for a query, without generation
curl "http://127.0.0.1:8000/api/v1/rag/chunks?query=warranty+length+electronics"

# ask the RAG system a question directly — requires a live generation
# provider (no "deterministic" default; see PROJECT_STATE.md's decision 17)
curl -X POST http://127.0.0.1:8000/api/v1/rag/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the warranty length on electronics?", "provider": "openai"}'

# run one RAG dataset case through real retrieval + grading (no API key needed by default)
curl -X POST http://127.0.0.1:8000/api/v1/rag/evaluate/rag-001 \
  -H "Content-Type: application/json" -d '{}'
```

Sprint 5's RAGAS integration (opt-in, disabled by default):

```bash
# run only the Sprint 5 / RAGAS test suite (fully mocked, no API key or cost)
uv run pytest -v tests/evaluation/ragas/

# start the server with RAGAS enabled (requires a real AQG_OPENAI_API_KEY —
# RAGAS's LLM judge/embeddings reuse it; incurs real API cost per case scored)
AQG_RAGAS_ENABLED=true AQG_OPENAI_API_KEY=sk-... uv run uvicorn app.main:app --reload

# with the server above running, evaluate a RAG case and see deterministic +
# RAGAS metrics side by side (the "metrics_by_framework" key)
curl -X POST http://127.0.0.1:8000/api/v1/rag/evaluate/rag-001 \
  -H "Content-Type: application/json" -d '{}'
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
| `AQG_RAG_CORPUS_DIR` | `rag_corpus` | Directory of `.md` knowledge-base files; relative paths resolve against `backend/` |
| `AQG_RAG_CHROMA_DIR` | `chroma_store` | ChromaDB persistence directory (gitignored, rebuilt from `rag_corpus/`) |
| `AQG_RAG_COLLECTION_NAME` | `rag-corpus` | ChromaDB collection name |
| `AQG_RAG_EMBEDDINGS_PROVIDER` | `deterministic` | `deterministic` (offline, default) or `openai` (needs `AQG_OPENAI_API_KEY`) |
| `AQG_RAG_TOP_K` | `4` | Number of chunks the retriever returns per query, before relevance filtering |
| `AQG_RAG_RELEVANCE_THRESHOLD` | `0.08` | Minimum cosine similarity for a chunk to be returned; see `app/rag/retriever.py` |
| `AQG_RAG_DATASET_NAME` | `customer_support_bot` | Dataset the `/rag/evaluate/{case_id}` endpoint resolves case ids against |
| `AQG_RAGAS_ENABLED` | `false` | Adds the 4 RAGAS evaluators to the runner when `true`. Requires `AQG_OPENAI_API_KEY`; app startup raises `RagasConfigurationError` otherwise |
| `AQG_RAGAS_METRICS` | `faithfulness,answer_relevancy,context_precision,context_recall` | Comma-separated subset to enable; an unknown name also raises `RagasConfigurationError` at startup |
| `AQG_RAGAS_LLM_MODEL` | unset (falls back to `AQG_OPENAI_MODEL`) | Judge model RAGAS uses for its LLM-based metrics |
| `AQG_RAGAS_EMBEDDING_MODEL` | `text-embedding-3-small` | Embedding model RAGAS uses for `answer_relevancy` |
| `AQG_RAGAS_FAITHFULNESS_THRESHOLD` | `0.80` | Pass/fail cutoff for the faithfulness metric |
| `AQG_RAGAS_ANSWER_RELEVANCY_THRESHOLD` | `0.70` | Pass/fail cutoff for the answer-relevancy metric |
| `AQG_RAGAS_CONTEXT_PRECISION_THRESHOLD` | `0.70` | Pass/fail cutoff for the context-precision metric |
| `AQG_RAGAS_CONTEXT_RECALL_THRESHOLD` | `0.70` | Pass/fail cutoff for the context-recall metric |

Settings are also loadable from a `backend/.env` file (not committed).
