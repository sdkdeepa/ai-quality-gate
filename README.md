# AI Quality Gate

An internal engineering platform that evaluates LLM and RAG applications
before release and returns a **PASS / WARN / BLOCK** decision based on
configurable quality thresholds.

This is not a chatbot and not a tutorial project — it's a release gate:
evaluation frameworks (DeepEval, RAGAS, OpenAI Evals, LangChain, Phoenix)
plug in as signal producers behind an internal evaluation interface, but
orchestration, thresholds, baseline comparison, and the release decision
itself are owned by the Quality Gate, not by any framework.

## Status

**Sprint 10 — Reports and Engineering Dashboard: complete.**

The service loads versioned golden datasets from disk and grades
system-under-test responses with 8 deterministic evaluators (exact/
required/forbidden-phrase matching, JSON schema compliance, expected-refusal
detection, citation presence, latency and cost thresholds), 4 RAGAS-backed
evaluators (faithfulness, answer relevancy, context precision, context
recall) for RAG cases, a DeepEval G-Eval custom-criteria evaluator for
qualitative/semantic checks (tone, policy adherence, or any natural-language
rubric), and two OpenAI-model-graded evaluators (closed-set label
classification for policy/behavior/quality checks, and fact-checklist
scoring for structured answer correctness — built directly on OpenAI's
Responses API, not the now-deprecated hosted Evals product) — all three
opt-in via `AQG_RAGAS_ENABLED`/`AQG_DEEPEVAL_ENABLED`/`AQG_OPENAI_EVALS_ENABLED`,
disabled by default, and independently selectable per run via an optional
`frameworks` request field. Responses come from a provider abstraction — a
`DeterministicProvider` (fixture-backed, for tests/CI), `OpenAIProvider`,
and `GeminiProvider` — selected per evaluation run; evaluation logic never
depends on the OpenAI/Gemini/RAGAS/DeepEval SDKs directly, and provider/
evaluator failures (timeout, rate limit, unavailable, malformed response,
authentication) are normalized rather than raised. A platform-owned release
Policy Engine (`app/policy/engine.py`) — the only place PASS/WARN/BLOCK is
ever computed — turns a run's results plus a configurable `ReleasePolicy`
and an optional approved `Baseline` into an auditable `GateDecision`,
persisted to SQLite (`AQG_POLICY_DB_PATH`) behind the API's `/gate/*`
endpoints (run gate, inspect/list decisions, approve baselines, compare
runs, manage policies). Optional Phoenix/OpenTelemetry tracing
(`AQG_TRACING_ENABLED`) instruments every run, case, provider call, RAG
retrieval, and evaluator execution, with trace IDs persisted on both the
run and its gate decision for audit correlation — Phoenix only ever
observes, never decides (see `docs/debugging-failed-runs.md`). Every
`GateDecision` can be exported as a downloadable JSON or HTML report
(`GET /reports/{decision_id}/json`|`/html`), and a separate `frontend/`
— a Vite + React + TypeScript internal engineering dashboard (Overview,
Evaluation Runs, Run Detail, Policies, Datasets) — gives a read-oriented
view over the whole system, entirely as a thin client over this same API.
A small LangChain + ChromaDB RAG pipeline exists as a system under test.
See `PROJECT_STATE.md` for full capability detail and outstanding work.

See [`PROJECT_STATE.md`](PROJECT_STATE.md) for current architecture,
completed capabilities, outstanding work, and exact run commands, and
[`DECISIONS.md`](DECISIONS.md) for the architecture decision log.

## Quick start

```bash
cd backend
uv sync                              # install dependencies
uv run uvicorn app.main:app --reload # run the API at http://127.0.0.1:8000
uv run pytest -v                     # run the test suite
uv run ruff check .                  # lint
```

Once running: `GET /health`, `GET /api/v1/status`, interactive docs at
`/docs`.

To run the engineering dashboard against that backend:

```bash
cd frontend
npm install
npm run dev    # dev server, defaults to http://localhost:8000/api/v1
npm test       # Vitest + React Testing Library
npm run build  # production build (tsc -b && vite build)
```

## Repository layout

```
ai-quality-gate/
├── PROJECT_STATE.md   # architecture, capabilities, outstanding work, run commands
├── DECISIONS.md        # architecture decision log
├── docs/                # task-oriented guides (e.g. debugging-failed-runs.md)
├── frontend/            # React/TypeScript internal engineering dashboard
└── backend/            # FastAPI service (domain model, API, tests)
```
