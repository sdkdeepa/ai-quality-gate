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

**Sprint 6 — DeepEval Integration: complete.**

The service loads versioned golden datasets from disk and grades
system-under-test responses with 8 deterministic evaluators (exact/
required/forbidden-phrase matching, JSON schema compliance, expected-refusal
detection, citation presence, latency and cost thresholds), 4 RAGAS-backed
evaluators (faithfulness, answer relevancy, context precision, context
recall) for RAG cases, and a DeepEval G-Eval custom-criteria evaluator for
qualitative/semantic checks (tone, policy adherence, or any natural-language
rubric) — all three opt-in via `AQG_RAGAS_ENABLED`/`AQG_DEEPEVAL_ENABLED`,
disabled by default, and independently selectable per run via an optional
`frameworks` request field. Responses come from a provider abstraction — a
`DeterministicProvider` (fixture-backed, for tests/CI), `OpenAIProvider`,
and `GeminiProvider` — selected per evaluation run; evaluation logic never
depends on the OpenAI/Gemini/RAGAS/DeepEval SDKs directly, and provider/
evaluator failures (timeout, rate limit, unavailable, malformed response,
authentication) are normalized rather than raised. A small LangChain +
ChromaDB RAG pipeline exists as a system under test. See `PROJECT_STATE.md`
for full capability detail and outstanding work.

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

## Repository layout

```
ai-quality-gate/
├── PROJECT_STATE.md   # architecture, capabilities, outstanding work, run commands
├── DECISIONS.md        # architecture decision log
└── backend/            # FastAPI service (domain model, API, tests)
```
