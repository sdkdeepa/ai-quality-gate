# PROJECT_STATE

Last updated: 2026-09-30 — Sprint 13 documentation and architecture review.

## Status

The planned 13-sprint build is complete. The repository is a **production-oriented reference implementation**, not a production-deployed service. No significant feature work was added in Sprint 13; the final sprint focused on documentation, architecture review, cleanup, and validation.

## Current architecture

```text
Golden Dataset
    -> EvaluationRunner
        -> Provider contract
           -> DeterministicProvider | OpenAIProvider | GeminiProvider | RAGProvider
        -> Evaluator protocol
           -> deterministic | RAGAS | DeepEval | OpenAI-model graders
    -> normalized MetricResult / CaseResult / EvaluationRun
    -> PolicyEngine + approved baseline
    -> GateDecision: PASS | WARN | BLOCK
    -> JSON/HTML reports + React dashboard

Cross-cutting: OpenTelemetry/Phoenix tracing, structured/redacted logging,
bounded provider retries, evaluator timeouts, request IDs/trace IDs,
request-size limits, readiness checks, basic write authentication.
```

The sample LangChain + Chroma RAG pipeline is a **system under test**, not part of the Quality Gate itself. Evaluation frameworks are replaceable adapters. `PolicyEngine` is the only component that owns PASS/WARN/BLOCK.

## Completed capabilities

- FastAPI/Pydantic backend with domain/service/repository separation
- Versioned JSON golden datasets and deterministic fixture provider
- Deterministic evaluators for exact/phrase/schema/refusal/citation/latency/cost checks
- Provider-neutral OpenAI and Gemini adapters with normalized failures and cost tracking
- LangChain + Chroma sample RAG workload with retrieval metadata
- RAGAS, DeepEval, and OpenAI-model grader adapters
- Configurable framework selection and explicit infrastructure-failure semantics
- Release policies, critical-case enforcement, approved baselines, regression comparison, latency/cost budgets
- SQLite persistence for policies, baselines, and gate decisions
- Optional Phoenix/OpenTelemetry tracing with trace-id correlation
- JSON/HTML reports and React engineering dashboard
- Docker backend/frontend images and docker-compose
- GitHub Actions deterministic PR CI plus optional manual live evaluation
- Request-size limits, redacted logging, API-key write boundary, dependency scanning
- Bounded provider retries, evaluator timeouts, partial-evaluation semantics, health/readiness endpoints, framework failure isolation

## Validation

The final repository includes backend PyTest coverage, frontend Vitest/React Testing Library coverage, API/integration tests, deterministic end-to-end smoke testing, Docker build/smoke validation in CI, and dependency scans (`pip-audit`, `npm audit`). Live-provider and model-judge tests remain opt-in so normal CI does not incur paid API calls.

Useful commands:

```bash
# backend
cd backend
uv sync
uv run pytest -v
uv run ruff check .
uv run ruff format --check .
uv run uvicorn app.main:app --reload

# frontend
cd frontend
npm install
npm test
npm run build

# full local stack
cp .env.example .env
docker compose up --build

# running-service smoke test
./scripts/smoke_test.sh http://localhost:8000
```

## Configuration

`.env.example` is the authoritative local configuration reference. Important opt-in areas are:

- `AQG_OPENAI_API_KEY`, `AQG_OPENAI_MODEL`
- `AQG_GEMINI_API_KEY`, `AQG_GEMINI_MODEL`
- `AQG_RAGAS_ENABLED`, `AQG_DEEPEVAL_ENABLED`, `AQG_OPENAI_EVALS_ENABLED`
- `AQG_TRACING_ENABLED`, `AQG_PHOENIX_COLLECTOR_ENDPOINT`
- `AQG_POLICY_DB_PATH`
- `AQG_API_KEY`
- reliability/request-limit settings defined by `Settings`

## Known limitations

- Datasets, runs, and case results are in-memory; only policy/baseline/decision records use SQLite.
- Authentication is a shared write key rather than per-user RBAC; the dashboard does not currently send that key.
- Request-size limiting checks `Content-Length` and does not close the chunked-transfer gap.
- Evaluator timeout abandons the caller's wait but cannot kill an already-running Python thread.
- Evaluation is synchronous; there is no queue/worker architecture or horizontal-scaling design.
- TLS termination, production identity, durable audit identity, and production datastore concerns are deliberately outside this reference implementation.
- Real provider/evaluator smoke tests require credentials and may incur cost; they are not part of standard PR CI.

## Documentation map

- `README.md` — project overview, setup, CI/testing summary, production gaps
- `ARCHITECTURE.md` — detailed architecture and decision flows
- `EVALUATION_STRATEGY.md` — evaluator and release-policy design
- `SECURITY.md` — security controls and limitations
- `DECISIONS.md` — concise architectural decision record
- `docs/ci-cd.md` — CI/CD details
- `docs/debugging-failed-runs.md` — Phoenix/OpenTelemetry debugging guide

No additional sprint is planned. Future work should be driven by an actual deployment/use case rather than expanding the reference implementation for its own sake.
