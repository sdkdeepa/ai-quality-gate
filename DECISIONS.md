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

## Sprint 2 — Golden Dataset and Deterministic Evaluation

### 8. Evaluators are data-driven ("applies_to"), not category-hardcoded

**Decision:** The `Evaluator` protocol requires both `applies_to(case) ->
bool` and `evaluate(input) -> MetricResult`. Whether an evaluator runs for
a given case is decided by inspecting the case's own fields/metadata (e.g.
`RequiredPhraseEvaluator` applies iff `metadata["required_phrases"]` is
non-empty; `ExpectedRefusalEvaluator` applies iff `expected_behavior` is
`REFUSE`/`UNSUPPORTED`) rather than a runner-level `if category ==
"structured_output": run JSONSchemaEvaluator` dispatch table.

**Reason:** The spec calls for evaluators like exact/normalized match
"where appropriate" — appropriateness is a property of the individual
case (does it have an `expected_answer`? a `json_schema`? required
phrases?), not of a coarse category label. Data-driven applicability lets
one dataset mix, e.g., a phrase-graded answerable case and an
exact-match answerable case without a special-cased runner.

**Alternatives considered:** A central registry mapping `category ->
[evaluator names]` — rejected because it forces every case in a category
to be graded identically and pushes a policy decision (which evaluators
matter for this case) out of the dataset author's hands and into runner
code.

**Trade-off:** Dataset authors must know the metadata keys each evaluator
looks for (`required_phrases`, `forbidden_phrases`, `json_schema`,
`match_mode`, `requires_citation`, `max_latency_ms`, `max_cost_usd`,
`refusal_phrases`) — there's no schema enforcing valid metadata shape
beyond what each evaluator reads defensively at evaluate-time. Acceptable
for Sprint 2's scope; a dataset-authoring guide or metadata schema could
be added later if this becomes error-prone at scale.

### 9. Evaluators never compute pass/fail policy beyond their own metric

**Decision:** Each evaluator returns exactly one `MetricResult` with its
own `score`/`threshold`/`passed`. `EvaluationRunner` combines them for a
case via a simple `passed = all(m.passed for m in metric_results)` — no
weighting, no partial credit across metrics, no evaluator-specific
override of what "case passed" means.

**Reason:** Keeps the plugin boundary from [[Sprint 1 decision 1]] intact
one level deeper: not just "frameworks don't own release policy" but
"individual evaluators don't own cross-metric policy" either. All
policy — including someday weighting some metrics more than others —
belongs to the Gate's future policy layer, not scattered across
evaluator implementations or buried in the runner's aggregation logic.

**Alternatives considered:** Let each evaluator carry a "weight" or let
the runner special-case which metrics are "blocking" vs "advisory" —
rejected as premature; Sprint 2 has no policy layer yet to consume such a
distinction, and adding it now would be a guess at requirements Sprint 3
hasn't defined.

**Trade-off:** Today, any single failing applicable metric fails the
whole case, with no nuance (e.g., latency exceeding threshold fails the
case exactly as hard as a forbidden-phrase leak). This is visible in the
seed dataset (`ans-003` fails solely on latency). Acceptable because
`MetricResult` still carries the full detail (which metric, what score
vs. threshold) for a future policy layer to weight differently — no
information is lost, just not yet acted on differently.

### 10. Fixture-driven runner instead of a fake/mock model provider

**Decision:** `EvaluationRunner.run()` takes a `dict[case_id,
FixtureResponse]` of pre-recorded responses rather than calling any
provider interface (real or fake). `DatasetService.get_fixtures()` loads
these from a `{name}.v{version}.fixtures.json` file that sits alongside
the dataset file.

**Reason:** The spec explicitly excludes model providers from Sprint 2
("Do NOT add external model providers... yet") but still requires an
evaluation runner to exercise deterministically. A fixture map is the
simplest thing that could work: it proves the evaluator pipeline,
critical-case detection, and API surface end-to-end without inventing a
throwaway provider abstraction that Sprint 3's real provider interface
would likely replace anyway.

**Alternatives considered:** Build a minimal `ModelProvider` protocol now
with a single deterministic/stub implementation — rejected as scope
creep and a risk of designing the wrong provider interface before Sprint
3 defines real requirements (streaming? retries? multi-turn?). A random/
templated fake response generator — rejected because non-deterministic
or generated responses would make the "22 cases, 15 pass / 7 fail, 2
critical failures" test assertions fragile and unable to target specific
evaluators deliberately.

**Trade-off:** `EvaluationRunner` cannot evaluate anything without a
complete fixture map — `MissingFixtureError` if any case lacks one. This
is a hard requirement, not a soft fallback, so the seed dataset's
fixtures file must stay in sync with its case list. When Sprint 3 adds a
real provider, the runner will need a second code path (or the fixture
provider will be reframed as one more `ResponseProvider` implementation
alongside a live one) — deferred deliberately.

### 11. Dataset/fixture files on disk, not in a database or embedded in code

**Decision:** Golden datasets and their fixtures are plain JSON files
under `backend/datasets/`, loaded by `DatasetService.load_all()` at app
startup into the existing `InMemoryRepository[GoldenDataset]`. Naming
convention `{name}.v{version}.json` / `{name}.v{version}.fixtures.json`
encodes versioning in the filename rather than a database column.

**Reason:** "Versioned golden datasets" is a Sprint 2 requirement, and
files are the simplest versionable, diffable, code-reviewable format —
exactly what you want for eval data that should change deliberately and
be tracked in git alongside the code that grades it. No database exists
yet ([[Sprint 1 decision 2]] deferred persistence generally), so this
avoids introducing one just for datasets.

**Alternatives considered:** Store datasets as Python literals/fixtures
inside the test suite — rejected because it conflates "data used to test
the Quality Gate's own code" with "data the Quality Gate evaluates
production systems against," which are different lifecycles (the latter
should be editable/reviewable by non-engineers eventually, e.g. via the
future dashboard). A database table — rejected as premature per Sprint
1's persistence decision.

**Trade-off:** `DatasetService` re-reads and re-validates every file on
every app startup (no caching beyond the in-memory repository populated
once at boot); at current scale (one seed dataset) this is instant, but a
large dataset library would need lazy-loading or pagination — not needed
yet.

## Sprint 3 — Provider Abstraction, OpenAI and Gemini

### 12. Providers normalize failures into the response instead of raising

**Decision:** `Provider.generate()` never raises for the five defined
failure modes (`timeout`, `rate_limit`, `unavailable`, `malformed_response`,
`authentication`). `OpenAIProvider` and `GeminiProvider` catch every
relevant SDK exception internally and return a `ProviderResponse` with
`error` set instead; `EvaluationRunner` checks `response.error` and
records a failed `CaseResult` rather than letting an exception propagate.

**Reason:** A run evaluates 20+ cases against a live model; one case
hitting a rate limit or a transient 503 must not abort every other case in
the run. Treating provider failure as *data* (a normal, expected outcome
with its own type) rather than as an *exception* (an abnormal control-flow
event) keeps the runner's per-case loop simple — no try/except around
each `provider.generate()` call — and keeps failure information in the
same place success information lives, so it can flow into `CaseResult`
and eventually the API response without a separate error-reporting path.

**Alternatives considered:** Let SDK exceptions propagate and catch them
in the runner or `EvaluationService` — rejected because it would require
the runner to know about `openai`/`google.genai` exception types,
reintroducing exactly the SDK coupling the provider abstraction exists to
prevent. A retry-with-backoff wrapper around each provider call — out of
scope for Sprint 3 (see `PROJECT_STATE.md` outstanding work); normalizing
the failure is a prerequisite for retry logic, not a substitute for it.

**Trade-off:** Every call site that uses a `Provider` must remember to
check `response.error` rather than relying on try/except to catch
mistakes — there's no compiler-enforced guarantee a caller handles it.
Accepted because the alternative (typed exceptions) would still require
the same discipline (a matching `except` clause) while also leaking SDK
exception types across the provider boundary.

### 13. `DeterministicProvider` reframes Sprint 2's fixtures, rather than adding a parallel path

**Decision:** `DeterministicProvider` takes the exact same `dict[case_id,
FixtureResponse]` `DatasetService.get_fixtures()` already produced in
Sprint 2 and wraps it as a `Provider`. `EvaluationRunner.run(dataset,
fixtures)` — the Sprint 2 entry point — is kept, but is now a thin wrapper
that builds a `DeterministicProvider` and delegates to the new
`run_with_provider(dataset, provider)`, which is what `OpenAIProvider`/
`GeminiProvider` runs also go through.

**Reason:** [[Sprint 2 decision 10]] flagged this explicitly as deferred
work: "when Sprint 3 adds a real provider, ... the fixture provider will
be reframed as one more `ResponseProvider` implementation alongside a
live one." Doing this instead of adding a second, independent live-run
code path means there is exactly one place (`_evaluate_case`) that turns
a response into a `CaseResult`, so fixture-driven and live-provider runs
can never silently diverge in how they compute `passed`/`critical_failure`.

**Alternatives considered:** Leave `run(dataset, fixtures)` as the only
fixture path and add a completely separate `run_live(dataset, provider)`
with its own case-evaluation logic — rejected as exactly the duplication
[[Sprint 2 decision 10]] warned against; two copies of "build an
EvaluationInput, run applicable evaluators, decide `passed`" would drift.

**Trade-off:** `EvaluationRunner.run()`'s public signature
(`fixtures: dict[str, FixtureResponse]`, keyword `provider`/`model` for
naming) is preserved only because `DeterministicProvider` accepts an
overridable `name`; the coupling between the two classes is intentional
and would need to move together if either's constructor changes.

### 14. Cost calculation is a pluggable, static pricing-table lookup, not a billing-API integration

**Decision:** `TableCostCalculator` estimates cost from a hand-maintained
`dict[model, (input_price_per_1m, output_price_per_1m)]`, injected into
each live provider (defaulting to `OPENAI_PRICING`/`GEMINI_PRICING`). An
unrecognized model name returns a configurable default price (`(0.0,
0.0)`) instead of raising.

**Reason:** Sprint 3 needs "estimated cost" on every `ProviderResponse`
so the existing `CostThresholdEvaluator` from Sprint 2 keeps working
against live-provider runs the same way it does against fixtures — but
querying a real billing API per request would add a second network call
and a second point of failure to every case, for a number this system
only needs as an estimate/gate signal, not an invoice.

**Alternatives considered:** Hardcode pricing inline in each provider —
rejected because it couples pricing (which changes on the provider's
schedule, not this codebase's) to request logic, and makes it impossible
to override pricing in a test or a future config file without editing
provider source. Fetching live pricing from each provider's API — no
such API exists for either OpenAI or Gemini as of this sprint.

**Trade-off:** Pricing tables will drift out of date as providers change
list prices, and per-org negotiated/volume pricing isn't represented at
all — `estimated_cost` is explicitly a release-gate budgeting signal, not
a billing source of truth. `CostCalculator` is a `Protocol`, so swapping
in a different (e.g. config-file-driven) implementation later doesn't
require touching provider code.

### 15. Provider selection is a per-request field, resolved through a factory — not fixed at process startup

**Decision:** `POST /api/v1/evaluations/runs` takes a `provider` field
(`"deterministic" | "openai" | "gemini"`, default `"deterministic"`).
`ProviderFactory.create(provider_name, dataset=...)` builds the requested
`Provider` per call, reading API keys/models from `Settings` and raising
`ProviderConfigurationError` (400) if a live provider is requested without
its key configured.

**Reason:** The same running server needs to support fixture-driven runs
(tests, CI, day-to-day dataset iteration — no API key, always available)
and live-provider runs (manual validation, eventually real release
gating) without a restart or a config flag that picks one mode for the
whole process. A per-request field makes "which system under test did
this run evaluate" an explicit, auditable part of every `EvaluationRun`
(`run.provider`/`run.model`) rather than implicit server configuration.

**Alternatives considered:** A single `AQG_PROVIDER` env var fixing the
provider for the whole process — rejected because it would make comparing
a deterministic regression-test run against a live-provider run require
two separately configured server instances. Constructing providers eagerly
at `create_app()` time (like `DatasetService`) — rejected for the live
providers specifically, since that would require API keys to be present
just to start the server at all, even for pure fixture-driven use.

**Trade-off:** A malformed/unconfigured `provider` value is only caught
at request time (400), not at server-startup time — a typo'd or
never-configured `AQG_OPENAI_API_KEY` isn't discovered until the first
`"provider": "openai"` request. Acceptable: fixture-driven runs (the
default, and the only one exercised by the automated test suite) are
completely unaffected by live-provider configuration.

## Sprint 4 — Sample RAG System using LangChain and ChromaDB

### 16. The RAG system is a system under test, not part of the Quality Gate

**Decision:** `app/rag/` is a self-contained sample application — a real
retrieve-then-generate pipeline over a small local corpus — built
specifically to give the Gate something realistic to evaluate. It is not a
chat feature, not a product surface, and the Gate's own evaluation code
(`app/evaluation/`, the release-policy layer this is all in service of)
never imports anything from `app/rag/`. The dependency direction is
one-way: `app/rag` depends on `app/providers` (for generation) exactly the
way any other system-under-test would; nothing in the Gate depends on
`app/rag`.

**Reason:** The sprint brief was explicit: "The Quality Gate is NOT
becoming a chatbot. The RAG system exists only as a system-under-test for
evaluation." Every architectural choice in this sprint follows from taking
that literally — the RAG API endpoints (`/rag/query`, `/rag/chunks`,
`/rag/evaluate/{case_id}`) are grouped under their own router and prefix,
documented as debugging/exploration tools for the sample system, and nothing
about the Gate's release-decision path (thresholds, `GateDecision`, audit
trail — still Sprint 5+ work) is aware the RAG system exists.

**Alternatives considered:** Building the RAG pipeline as a general
"knowledge base" feature of the Gate itself (e.g., letting the Gate answer
questions about its own datasets) — rejected outright as scope creep
directly contradicting the brief. Skipping a dedicated `/rag/query`
exploration endpoint and only exposing RAG through dataset evaluation —
rejected because manually validating a new retrieval pipeline without any
way to ask it an ad-hoc question and see the retrieved chunks would make
Sprint 4's own manual validation nearly impossible.

**Trade-off:** This sprint effectively ships two small systems in one
codebase (the Gate, and a sample RAG app for the Gate to grade) with real
but disciplined coupling between them (`RAGProvider`, one class, one
direction). Future sprints must keep resisting the urge to let the RAG
system grow product features — its only job is to be gradeable.

### 17. Where LangChain is used, and where our own code takes over

**Decision:** LangChain provides three things, and three things only:

- **Document schema** (`langchain_core.documents.Document`) — the shared
  in-memory shape for a loaded document and, later, a chunk.
- **Chunking** (`langchain_text_splitters.RecursiveCharacterTextSplitter`,
  `app/rag/chunking.py`) — a separator-aware, overlap-aware splitting
  algorithm.
- **The Chroma vector store integration** (`langchain_chroma.Chroma`,
  wrapped by `app/rag/vector_store.py`) — add/query against ChromaDB
  through LangChain's `Embeddings` interface.

Everything else in the pipeline is our own code: loading corpus files
(`app/rag/loader.py` reads `.md` files directly — no `DirectoryLoader`/
`TextLoader`, both of which live in `langchain-community`, a package
LangChain itself is sunsetting in favor of standalone integration
packages); the embeddings implementations (`app/rag/embeddings.py`,
`DeterministicEmbeddings`/`OpenAIEmbeddings` — LangChain's `Embeddings`
*interface* is reused, but no LangChain embeddings *implementation* is
installed); retrieval and the relevance floor (`app/rag/retriever.py` — a
~20-line class, not a LangChain `BaseRetriever`); prompt construction
(`app/rag/prompt.py` — plain string templating, not a `PromptTemplate`);
and the pipeline orchestration and Provider-contract integration
(`app/rag/pipeline.py`, `provider_adapter.py` — pure Sprint 3 `Provider`
composition, no LangChain involved at all).

**Reason:** LangChain earns its place exactly where it replaces
well-tested, undifferentiated logic that would otherwise just be
reimplemented worse (a recursive-splitting algorithm with sensible
separator fallback; a maintained Chroma client wrapper that speaks
LangChain's `Embeddings`/`Document` protocol so any future LangChain
component — retrievers, chains, other vector stores — could be dropped in
without touching our data model). It does *not* earn a place in the parts
of this system that carry actual product logic specific to the Quality
Gate — what "relevant enough to retrieve" means for this corpus, what the
generation prompt says, how a RAG case's answer is graded — because those
are exactly the decisions [[Sprint 1 decision 1]] and [[Sprint 3 decision
12]] already established should stay in our own code, not a framework's.

**Alternatives considered:** A LangChain `RetrievalQA`/LCEL chain for the
whole pipeline — rejected because it would blur exactly the seam the
`Provider` abstraction exists to keep sharp: the generation step must stay
a plain Sprint 3 `Provider` so `RAGProvider` can hand a RAG case to
`EvaluationRunner` unchanged. `langchain-community`'s `DirectoryLoader`/
`TextLoader` for loading — rejected both because the package is being
sunset and because reading 9 short markdown files ourselves is simpler
than learning a loader's configuration surface. A LangChain-native
`Embeddings` implementation (e.g. `HuggingFaceEmbeddings`) instead of the
hand-rolled `DeterministicEmbeddings` — rejected for the default path
because it would pull in a real model (network/disk weight download) for
what Sprint 3's `DeterministicProvider` established should be a zero-
dependency, always-available CI default.

**Trade-off:** `DeterministicEmbeddings`' hashing-trick bag-of-words
approach is lexical (token-overlap), not semantic — it has no stemming, so
"return" and "returns" don't match, and reference/test queries had to be
worded around this empirically (see `app/rag/retriever.py`'s
`DEFAULT_RELEVANCE_THRESHOLD` docstring and `tests/rag/
test_unsupported_queries.py`). This is an accepted, documented limitation
of the always-available default, not a bug: real semantic retrieval
quality is exactly what `AQG_RAG_EMBEDDINGS_PROVIDER=openai` (or a real
embedding evaluator in a later sprint) is for.

### 18. `RAGProvider` adapts the pipeline to the `Provider` contract, rather than adding a RAG-specific evaluation path

**Decision:** `app/rag/provider_adapter.py`'s `RAGProvider` implements the
same `Provider` protocol (`name`, `model`, `generate(request) -> response`)
as `DeterministicProvider`/`OpenAIProvider`/`GeminiProvider`. It wraps a
`Retriever` and a generation `Provider` internally, but from
`EvaluationRunner`'s point of view it's just another `Provider` — `POST
/rag/evaluate/{case_id}` calls `EvaluationRunner.evaluate_case` (made
public this sprint; it was previously a private helper only `run_with_
provider` called internally) exactly the way a plain-provider case would
be graded.

**Reason:** [[Sprint 3 decision 12]] and [[Sprint 3 decision 13]] already
established the shape this should take: normalize everything (fixtures,
live models, and now retrieval-augmented generation) behind one `Provider`
contract so the runner and the 8 deterministic evaluators never need to
know or care what actually produced a response. Adding a parallel
"RAGEvaluationRunner" or a RAG-specific evaluator type would have
duplicated the exact case -> request -> response -> evaluate -> CaseResult
logic `evaluate_case` already implements, for no behavioral difference —
`CitationPresenceEvaluator`, `RequiredPhraseEvaluator`, etc. already work
correctly against `ProviderResponse.retrieved_context`, whether that
content came from a fixture or a real ChromaDB query.

**Alternatives considered:** A dedicated `RAGCaseResult`/`RAGRunner`
carrying richer RAG-specific detail (per-chunk relevance scores) all the
way through grading — rejected; the API layer already gets that detail
more simply by calling `Retriever.retrieve` a second time directly
(`RAGService.evaluate_case` — see the code) rather than plumbing chunk
scores through `ProviderResponse`, which only ever needed to carry chunk
*text* for `CitationPresenceEvaluator` to work. A new `Evaluator`
implementation scoring retrieval precision/recall against
`reference_context` — explicitly deferred (see `PROJECT_STATE.md`
outstanding work); Sprint 4 proves the pipeline and the dataset scenarios,
not a new metric.

**Trade-off:** `RAGService.evaluate_case` calls `Retriever.retrieve` twice
per request (once inside `RAGProvider.generate`, once directly for the
API response's chunk detail) — a deliberate, cheap (in-process, no
network) duplication chosen over threading extra fields through
`ProviderResponse` for a contract every other provider also has to satisfy.

### 19. Golden dataset extended in place (v1.1.0), with fixtures covering every case — not a separate RAG-only dataset

**Decision:** The 18 new RAG cases live in the *same* `customer_support_bot`
dataset, as v1.1.0 (`customer_support_bot.v1.1.0.json`), alongside the
original 22 v1.0.0 cases — not a new `customer_support_bot_rag` dataset.
`customer_support_bot.v1.1.0.fixtures.json` has a canned response for all
40 cases, including the 18 new ones, so `POST /evaluations/runs` (Sprint
3's bulk endpoint, provider defaulting to `"deterministic"`) grades the
whole v1.1.0 dataset — RAG cases included — exactly the way it always has,
with no RAG-specific code path.

**Reason:** "Extend golden dataset with 15-20 RAG cases" (the sprint
brief's own words) reads naturally as extending the existing dataset, and
the existing dataset already had a `retrieval` category (`ret-001..004`)
simulating RAG behavior via fixtures before a real RAG system existed —
the new `rag` category cases are that same idea, now exercisable against
the real pipeline too via `/rag/evaluate/{case_id}`. Populating fixtures
for the new cases costs nothing (it's authoring canned text) and keeps
`GoldenDataset`'s existing invariant intact: every case in a dataset has a
fixture, so the fixture-driven path never has a "some cases work
differently" special case.

**Alternatives considered:** A separate `rag_corpus_eval` dataset —
rejected; it would fragment the "one golden dataset for this system"
mental model for no benefit, since nothing about `GoldenDataset` or
`DatasetService` requires cases to be homogeneous (`category` is already
a free-form string spanning answerable/unsupported/refusal/structured_
output/retrieval/negative). Leaving the 18 new cases *out* of the
fixtures file (since they're "meant to run against the real pipeline") —
rejected because it would make `POST /evaluations/runs` against v1.1.0
raise `MissingFixtureError`, breaking the bulk endpoint for a version bump
that should be additive.

**Trade-off:** Authoring 18 fixtures in addition to 18 cases roughly
doubled the size of this sprint's dataset-authoring work, and two rounds
of manual fixture-text tuning were needed to get the intended pass/fail
outcome exactly right (`rag-014`'s first draft fixture mentioned the
superseded "$6.99" figure while *explaining* it was outdated, which
correctly-but-unintentionally tripped its own `forbidden_phrases` check —
fixed by simplifying the fixture to state only the current figure). This
is the same trade-off [[Sprint 2 decision 10]] already accepted for the
original 22 cases, just at double the scale.

### 20. ChromaDB persists to disk with idempotent, hash-checked re-ingestion

**Decision:** `ChromaVectorStore` (`app/rag/vector_store.py`) persists to
`backend/chroma_store/` (gitignored) via `langchain_chroma.Chroma`'s
`persist_directory`. `RAGCorpusService.ingest_if_needed()`
(`app/rag/corpus_service.py`) computes a hash of the loaded+chunked corpus
and compares it against a hash recorded in a plain marker file
(`chroma_store/.corpus_hash`) the last time ingestion ran; it only wipes
and re-embeds the collection when the hash differs, mirroring
`DatasetService.load_all()`'s "files on disk are the source of truth,
reloaded at every startup" pattern from [[Sprint 2 decision 11]] — but
without paying the (here, non-trivial for a real embedding model)
re-embedding cost on every restart when nothing changed.

**Reason:** Sprint 2's dataset-loading precedent works because parsing
JSON is instant; embedding text is not, especially once
`AQG_RAG_EMBEDDINGS_PROVIDER=openai` is in play (a network call per
document). Persisting *and* checking a content hash gets both properties
Sprint 2 wanted from a different mechanism: the corpus files are still the
single source of truth (delete `chroma_store/` and the next startup
rebuilds it from scratch), but an unchanged corpus costs one hash
comparison instead of N embedding calls on every app restart or test run
that calls `create_app()`.

**Alternatives considered:** In-memory-only Chroma (no
`persist_directory`) — rejected; the sprint brief explicitly lists
"ChromaDB persistence" as a requirement, and losing the vector store on
every restart would make `AQG_RAG_EMBEDDINGS_PROVIDER=openai` prohibitively
slow/costly to develop against. Always wiping and re-ingesting on startup
regardless of content — rejected for the same reason Sprint 2 didn't need
this trade-off: it's wasted work (and wasted API cost, once real
embeddings are used) for the overwhelmingly common case of "the corpus
didn't change since last time."

**Trade-off:** The hash-marker file is a second piece of persisted state
alongside Chroma's own SQLite-backed storage, kept in sync by convention
(only `ChromaVectorStore.replace_all` writes either) rather than enforced
by a transaction spanning both — acceptable at this scale (single-process,
no concurrent writers) but would need revisiting if ingestion ever became
concurrent or multi-process.

## Sprint 5 — RAGAS Integration

### 21. Zero changes to `EvaluationRunner`; RAGAS evaluators are added by changing evaluator construction in `main.py`

**Decision:** Before writing any Sprint 5 code, we inspected
`app/evaluation/base.py` and `app/evaluation/runner.py` to find the
smallest clean extension for a framework-backed evaluator. `EvaluationRunner.__init__`
already accepts an injected `evaluators: list[Evaluator] | None` and
`evaluate_case` already applies whichever evaluators are present via
`applies_to`/`evaluate` — nothing in the runner assumes "deterministic" or
hardcodes `DEFAULT_EVALUATORS`. So Sprint 5 adds 4 new `Evaluator`
implementations (`app/evaluation/ragas/evaluator.py`) and changes exactly
one line's worth of wiring in `create_app()` (`app/main.py`):
`evaluators = list(DEFAULT_EVALUATORS) + build_ragas_evaluators(settings)`,
passed into `EvaluationRunner(evaluators=evaluators)`. `runner.py` itself
is byte-for-byte unchanged from Sprint 4.

**Reason:** [[Sprint 4 decision 18]] and the "Plugin boundary" note in
`PROJECT_STATE.md` already predicted this: "When DeepEval/RAGAS/OpenAI
Evals/Phoenix are integrated in a later sprint, they will implement this
same `Evaluator` protocol side-by-side with the deterministic ones." Sprint
5 is the first sprint to actually test that claim, and it held — building a
parallel evaluation path (a second runner, a RAG-specific branch, a new
orchestration service) would have been strictly more code for no
additional capability, and would have contradicted the sprint brief's
explicit "do not create a parallel evaluation architecture if the existing
architecture can be extended cleanly."

**Alternatives considered:** A `RagasEvaluationRunner` wrapping/duplicating
`EvaluationRunner` — rejected; two runners means two places a future
Policy Engine sprint has to look, and nothing about RAGAS's inputs
(query/response/retrieved-context/reference) needed anything `EvaluationInput`
didn't already carry. A `case.metadata["ragas"]`-driven branch inside
`evaluate_case` — rejected; `applies_to`/`evaluate` on the `Evaluator`
protocol is exactly that branch, already generalized, so adding a
special-cased branch alongside it would be redundant and would violate the
existing "evaluators are data-driven, not category-hardcoded" principle
([[Sprint 2 decision 8]]).

**Trade-off:** `build_ragas_evaluators(settings)` runs at `create_app()`
time, which means enabling RAGAS (`AQG_RAGAS_ENABLED=true`) without a valid
`AQG_OPENAI_API_KEY` fails app *startup*, not the first request — a
deliberate fail-fast choice (see [[Sprint 5 decision 22]]) but one that
differs from how a per-request provider misconfiguration behaves today
(`ProviderConfigurationError`, a 400 on the specific request that asked for
`"provider": "openai"`). This asymmetry is intentional: RAGAS's
configuration is a fixed part of the running process (which evaluators
exist for every run), not a per-request choice the way `provider` is.

### 22. RAGAS-specific types are confined to `RagasClient`; its failures reuse `ProviderErrorType`, not a new enum

**Decision:** `app/evaluation/ragas/client.py` is the only module in the
codebase that imports `ragas` or constructs the `openai.OpenAI` client used
purely as RAGAS's LLM judge/embeddings backend (via `ragas.llms.llm_factory`
and `ragas.embeddings.base.embedding_factory`, RAGAS's modern
`ragas.metrics.collections` API). `app/evaluation/ragas/evaluator.py` never
imports `ragas` — it only ever receives a `RagasScore` (success) or catches
a `RagasEvaluatorError` (infrastructure failure) from `RagasClient`.
`RagasEvaluatorError.error_type` reuses the **existing**
`app.providers.types.ProviderErrorType` enum (`TIMEOUT`/`AUTHENTICATION`/
`RATE_LIMIT`/`UNAVAILABLE`/`MALFORMED_RESPONSE`) rather than introducing a
second, RAGAS-specific error-type enum.

**Reason:** Mirrors [[Sprint 3 decision 12]]
(`OpenAIProvider`/`GeminiProvider` are the only modules importing their
SDKs; every SDK exception is caught and normalized before it can reach
evaluation logic) — the same isolation principle applies verbatim to a
framework-backed evaluator's judge client. The error-type reuse is because
the sprint brief's own failure-mode list ("RAGAS dependency failure",
"evaluator model timeout", "authentication failure", "rate limit",
"malformed evaluator response", "unavailable evaluator service") maps
1:1 onto `ProviderErrorType`'s existing 5 values — inventing
`RagasErrorType` with the same 5 members would be duplication with no
semantic gain, and would cost a second thing for any future consumer
(a Policy Engine, a dashboard) to know how to interpret.

A RAGAS metric result now normalizes into exactly one of three states,
all carried in `MetricResult.metadata["ragas_status"]` rather than a
domain model change (`MetricResult.metadata: dict[str, Any]` already
existed for exactly this — see [[Sprint 1 decision 2]]'s Pydantic-model
layering): `"scored"` (ran, judged against `threshold`), `"skipped_missing_input"`
(the case genuinely lacks a required input — e.g. `case.expected_answer`
for `context_precision`/`context_recall` on the irrelevant/missing/unsupported
RAG scenarios — `passed=True`, since "not applicable" must not fail a
case), and `"infrastructure_error"` (RAGAS/its dependencies/the judge model
failed to execute — `passed=False`, so an outage never silently produces
PASS, but distinguishable via `metadata` from a real quality score of 0).

**Alternatives considered:** Representing an infrastructure failure as
`score=0.0, passed=False` with no metadata flag — explicitly rejected by
the sprint brief itself ("An infrastructure failure must NOT be represented
as score=0... Do not allow a RAGAS infrastructure problem to silently
produce PASS"); a bare 0 is indistinguishable from a real faithfulness
score of 0.0, which a future Policy Engine would then be unable to treat
differently (e.g. retry/WARN vs. hard BLOCK). Raising the underlying
`ragas`/`openai` exception straight out of `Evaluator.evaluate()` —
rejected; every other evaluator in the codebase (deterministic and
provider-backed alike) guarantees it never raises for an expected failure
mode, and a RAGAS outage taking down an entire evaluation run would be a
regression from that guarantee. A second `RagasErrorType` enum — rejected
per the "Reason" above; reuse costs nothing and keeps one vocabulary for
"something in the response-generation/evaluation pipeline failed to
execute" across providers and evaluators alike.

**Trade-off:** Reusing `ProviderErrorType` means a couple of its members
carry a slightly stretched meaning for a RAGAS context (e.g. `AUTHENTICATION`
here means "the judge model's API key was rejected," not "the system under
test's provider was") — judged acceptable since the *shape* of the failure
(a credential problem, distinct from a timeout or a rate limit) is
identical either way, and a single enum is easier for any future consumer
to switch on than two enums with the same 5 cases under different names.

## Sprint 6 — DeepEval Integration

### 23. Only one DeepEval metric ships this sprint: G-Eval custom criteria; answer relevancy, faithfulness, and hallucination are omitted as duplicates of Sprint 5's RAGAS metrics

**Decision:** Before implementing anything, we compared each of the sprint
brief's 4 "potential areas" against what Sprint 5's RAGAS evaluators and
Sprint 1-4's deterministic evaluators already cover:

- **Answer relevancy** (`deepeval.metrics.AnswerRelevancyMetric`): measures
  whether the response addresses the user's query. `RagasAnswerRelevancyEvaluator`
  (Sprint 5) already measures exactly this, on exactly the same case
  population (`applies_to` isn't even RAG-restricted for either). **Omitted.**
- **Faithfulness/groundedness** (`deepeval.metrics.FaithfulnessMetric`):
  measures whether claims in the response are supported by retrieved
  context. `RagasFaithfulnessEvaluator` (Sprint 5) measures the same thing,
  same population (any case with `retrieved_context`). **Omitted.**
- **Hallucination** (`deepeval.metrics.HallucinationMetric`): DeepEval's own
  docs describe this as "similar to faithfulness" but framed as checking
  the response against an arbitrary `context` for contradictions, rather
  than RAG-specific retrieval grounding. In practice, for this codebase the
  input population is identical to Faithfulness/ContextPrecision/ContextRecall
  (any case with `reference_context` populated) and the question it answers
  — "does this response introduce claims unsupported by/contradicting the
  given context?" — is not meaningfully different from what Faithfulness
  already asks. **Omitted.**
- **Custom expected-behavior criteria** (`deepeval.metrics.GEval`): a
  natural-language rubric, LLM-judged with chain-of-thought reasoning. This
  is the one capability with **no existing equivalent** anywhere in the
  Gate: every deterministic evaluator does literal string/schema matching
  (`ExactMatchEvaluator`, `RequiredPhraseEvaluator`, `JSONSchemaEvaluator`,
  ...); every RAGAS metric is a retrieval-grounding question. Nothing in
  Sprint 1-5 can judge qualitative properties like tone, professionalism,
  or policy adherence ("does the response avoid making promises about
  refund timing?"). **Implemented**, as `DeepEvalCriteriaEvaluator`.

**Reason:** The sprint brief explicitly required this comparison
("compare it against existing RAGAS and deterministic metrics... if it
substantially duplicates an existing metric, either omit it or document
clearly why both are retained") and to "avoid duplicate metrics merely to
increase framework count." Three of the four candidates would have added a
second framework's opinion on a question Sprint 5 already answers, for the
same cases, at real per-case LLM cost — that's framework-count inflation,
not new signal. The fourth fills a genuine gap.

**Alternatives considered:** Implementing all 4 and treating agreement/
disagreement between RAGAS's and DeepEval's opinions on the same question
as its own signal (an ensemble/cross-validation approach) — a legitimate
idea in the abstract, but out of scope for what this sprint asked for and
not something a Policy Engine exists yet to consume; noted as a possible
future direction rather than built speculatively. Implementing Hallucination
specifically (since it's namely distinct from Faithfulness in DeepEval's
own framing) — rejected because the distinction is in *intent*
(RAG-specific vs. general-purpose), not in what it would actually measure
against this codebase's inputs, which are identical either way.

**Trade-off:** If a future need arises for a *general* (non-RAG) hallucination/
groundedness check — e.g. a non-"rag"-category case with a reference answer
but no retrieval step, which RAGAS's evaluators don't currently reach
because nothing populates `retrieved_context` for it — DeepEval's
Hallucination metric would become non-duplicative and worth revisiting.
Filed as a known limitation rather than implemented speculatively (see
PROJECT_STATE.md "Outstanding work").

### 24. `DeepEvalCriteriaEvaluator` is opt-in per case via `case.metadata`; `DeepEvalClient` isolates `deepeval` exactly like `RagasClient` isolates `ragas`

**Decision:** `DeepEvalCriteriaEvaluator.applies_to(case)` returns
`bool(case.metadata.get("deepeval_criteria"))` — a case with no criteria
string is simply not applicable, the same data-driven pattern
`CitationPresenceEvaluator` (Sprint 2) and RAGAS's `_is_rag_case` (Sprint 5)
both use. The criteria string itself, and two optional per-case overrides
(`deepeval_criteria_name` for the metric label, `deepeval_threshold` for a
per-case pass/fail cutoff), all live in `case.metadata` — Quality-Gate-owned
dataset data, never DeepEval's — satisfying "thresholds owned by Quality
Gate configuration" even when a threshold varies per case rather than being
one fixed `Settings` value.

`app/evaluation/deepeval/client.py` is the only module importing `deepeval`
or constructing the `deepeval.models.OpenAIModel` used purely as the G-Eval
judge, passing `api_key` explicitly rather than relying on deepeval's own
`OPENAI_API_KEY` environment-variable convention — this avoids introducing
a second credential to manage, reusing `AQG_OPENAI_API_KEY` exactly like
`RagasClient` does. `GEval` metric instances are cached by
`(name, criteria, evaluation_params, threshold)` since Sprint 6's criteria
can vary per case (unlike RAGAS's four fixed metrics), so identical
criteria across many cases in a dataset only builds one `GEval` object.

**Reason:** Mirrors [[Sprint 5 decision 22]] point for point — the
isolation principle ("only one module imports the framework/builds its
judge client") and the error-type reuse (`DeepEvalEvaluatorError.error_type`
reuses `ProviderErrorType`, not a third enum) apply identically regardless
of which framework is being adapted. Per-case criteria (rather than one
fixed criteria string in `Settings`, the way RAGAS's thresholds are) is a
deliberate difference: RAGAS's four metrics ask the same fixed question for
every case they apply to ("is this faithful", "is context precise"), while
G-Eval's entire value proposition is a *custom* rubric — fixing it at the
process level would make it no more useful than the (already-covered)
answer-relevancy/faithfulness metrics.

**Alternatives considered:** A single fixed `AQG_DEEPEVAL_CRITERIA` setting
applied to every case — rejected; this would make the evaluator
uniform across an entire dataset, discarding G-Eval's actual value (letting
a dataset author write a different rubric per case, e.g. "empathetic tone"
for support-ticket cases vs. "cites the exact policy clause" for
compliance-answer cases). Storing criteria in a separate config file keyed
by case id — rejected as unnecessary indirection; `case.metadata` already
exists precisely for this kind of per-case evaluator configuration
(`json_schema`, `required_phrases`, `rag_scenario`, ... all live there
already).

**Trade-off:** Unlike RAGAS's metrics, `DeepEvalCriteriaEvaluator`
contributes nothing to a dataset that never sets `deepeval_criteria` on any
case — even with `AQG_DEEPEVAL_ENABLED=true`, a dataset author has to
explicitly opt individual cases in. Judged correct: a criteria-less "custom
criteria" evaluator has nothing meaningful to check, so silently applying a
generic rubric to every case would produce noise, not signal.

### 25. Evaluator-combination selection is a `frameworks` field on the existing run/evaluate endpoints, backed by a `framework` attribute added to the `Evaluator` protocol — no new CLI, no new runner

**Decision:** `Evaluator` (`app/evaluation/base.py`) gained a `framework: str`
attribute alongside `name: str`. Every existing evaluator — all 8
deterministic, all 4 RAGAS, the 1 DeepEval — now exposes it as a class
attribute. `EvaluationRunner.run`/`run_with_provider`/`evaluate_case` all
gained an optional `frameworks: set[str] | None` keyword parameter; when
given, evaluation filters `self._evaluators` down to
`e.framework in frameworks` before applying `applies_to`/`evaluate`.
`POST /evaluations/runs` and `POST /rag/evaluate/{case_id}` both gained an
optional `frameworks` request field threading straight through
`EvaluationService.run`/`RAGService.evaluate_case` to the runner. `None`
(the default, and what every Sprint 1-5 caller/test still passes implicitly)
runs every evaluator the runner was constructed with — byte-identical to
pre-Sprint-6 behavior.

**Reason:** The sprint brief asked for evaluator selection ("deterministic
/ ragas / deepeval / combinations") and explicitly preferred API-based
selection over introducing a new CLI "if that fits the current architecture
better." It does: this is a FastAPI service with no existing CLI surface
for running evaluations at all (the closest thing, `uv run pytest`, is a
test-suite entry point, not a product feature), so a request field is the
only selection mechanism that fits without inventing a new interface
category. The `framework` attribute on `Evaluator` was the smallest gap
that made filtering possible at all: `MetricResult.framework` already
existed (Sprint 5), but nothing let the runner ask an *evaluator* what
framework it belonged to without running it first and inspecting the
result it produced — which would defeat the point of filtering *before*
calling potentially-expensive/costly evaluators. Adding the attribute is
the "real limitation Sprint 6 exposes" that justifies touching
`deterministic.py`/`ragas/evaluator.py`, per the sprint brief's "do not
redesign... unless Sprint 6 exposes a real limitation" instruction — every
change to those two files is exactly one class-attribute line added per
existing evaluator, no logic touched.

**Alternatives considered:** A separate `EvaluationRunner` per framework
combination, built at startup for every combination someone might request
— rejected; combinatorial (2^3 = 8 runners for 3 frameworks, worse for
more) for no benefit over filtering a single evaluator list at call time,
and would violate "do not duplicate the evaluation runner" directly.
Encoding framework selection in `case.metadata` instead of a request field
— rejected; framework selection is a property of *how you want this run
graded*, not a property of the *case*, so it belongs with `provider` (an
existing request-level choice) rather than mixed into per-case data meant
to travel with the dataset. A `--frameworks` CLI flag on some new script —
rejected per the brief's explicit API-first preference, and because it
would be a second, redundant way to trigger the same `EvaluationRunner`
this service already exposes over HTTP.

**Trade-off:** Requesting a framework that isn't enabled process-wide
(e.g. `"frameworks": ["deepeval"]` when `AQG_DEEPEVAL_ENABLED=false`) is
not an error — it silently contributes zero evaluators from that
framework, and a case with zero applicable evaluators vacuously passes
(the same pre-existing Sprint 1 rule for any case no evaluator applies to).
This means a caller who typos a framework name or forgets to enable one
gets a "passed" run rather than a loud failure. Accepted rather than
raising a 400/422, for consistency with the existing rule that an empty
`metric_results` list is not itself an error condition anywhere else in
the Gate; a future Policy Engine sprint is a more natural place to decide
whether "zero evaluators ran" should ever block a release.
