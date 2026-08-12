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

**Sprint 1 — Foundation and Domain Model: complete.**

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
