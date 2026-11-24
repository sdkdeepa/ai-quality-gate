# AI Quality Gate

A production-oriented reference implementation for evaluating LLM and RAG applications before release. It runs versioned golden datasets, normalizes signals from deterministic and model-based evaluators, compares results with policy and approved baselines, and returns an auditable **PASS / WARN / BLOCK** decision.

This repository is an engineering reference project, not a production-deployed service.

## What it does

The Quality Gate separates **evaluation signals** from **release policy**. RAGAS, DeepEval, OpenAI-model graders, and deterministic checks produce normalized `MetricResult`s. The platform-owned `PolicyEngine` decides whether a run can ship.

Core capabilities:

- Versioned golden datasets with critical cases
- Deterministic checks for exact/phrase/schema/refusal/citation/latency/cost behavior
- OpenAI and Gemini providers behind a provider-neutral interface
- Sample LangChain + Chroma RAG workload used as a system under test
- RAGAS, DeepEval, and OpenAI-model graders behind evaluator adapters
- Baselines, regression detection, latency/cost budgets, and PASS/WARN/BLOCK policy
- Optional Phoenix/OpenTelemetry tracing
- JSON/HTML reports and a React engineering dashboard
- Deterministic GitHub Actions CI, optional live-provider workflow, and Docker packaging
- Request limits, redacted logging, bounded retries, evaluator timeouts, readiness checks, and a basic write-auth boundary

## Architecture

```mermaid
flowchart LR
    GD["Golden Dataset"] --> R["EvaluationRunner"]
    P["System Under Test / Provider"] <--> R
    R --> E["Evaluator adapters"]
    E --> PE["PolicyEngine"]
    B["Approved Baseline"] --> PE
    PE --> D["PASS / WARN / BLOCK"]
    D --> RP["JSON / HTML Reports"]
    D --> UI["React Dashboard"]
    R -. optional tracing .-> PH["Phoenix / OpenTelemetry"]
```

The important boundary is deliberate: **frameworks provide signals; the Quality Gate owns release policy.** Phoenix observes execution but never participates in the decision.

See [ARCHITECTURE.md](ARCHITECTURE.md) for component, evaluation-pipeline, and decision-flow diagrams.

## Evaluation model

A run loads a named/versioned golden dataset, sends each case through a provider, and applies the evaluators that are relevant to that case. Evaluator outputs are normalized into the same internal model regardless of framework. Infrastructure failures are represented separately from quality failures, so a rate limit or judge timeout is not treated as a bad model answer.

The policy engine then evaluates pass rate, required metrics, critical cases, baseline regressions, latency/cost budgets, and evaluator availability. A run with no scored metrics cannot pass.

See [EVALUATION_STRATEGY.md](EVALUATION_STRATEGY.md) for the framework and policy rationale.

## Repository structure

```text
ai-quality-gate/
├── README.md
├── ARCHITECTURE.md
├── EVALUATION_STRATEGY.md
├── SECURITY.md
├── PROJECT_STATE.md
├── DECISIONS.md
├── docker-compose.yml
├── .github/workflows/       # deterministic PR CI + manual live evaluation
├── docs/                    # CI/CD and Phoenix debugging guides
├── scripts/smoke_test.sh
├── frontend/                # React + TypeScript dashboard
└── backend/
    ├── aqg/                 # the quality-gate core and aqg CLI (no server needed)
    └── app/                 # the API server
        ├── domain/
        ├── providers/
        ├── evaluation/
        ├── rag/
        ├── policy/
        ├── reports/
        ├── observability/
        ├── reliability/
        ├── repositories/
        ├── services/
        ├── api/
        └── core/
```

## Install

The package installs in two ways. The **core** is the `aqg` command-line gate: it reads
JUnit XML from pytest, Vitest and Playwright and decides PASS, WARN or BLOCK, with only
pydantic, jsonschema and PyYAML as dependencies. The **server** (the API, dashboard
backend, RAG demo and model-based evaluators) is an optional extra.

```bash
# The aqg CLI only. The package lives in backend/, hence #subdirectory.
# Pin a commit (or, once released, a tag) rather than a branch.
pip install "ai-quality-gate @ git+https://github.com/sdkdeepa/ai-quality-gate@<commit-sha>#subdirectory=backend"

# The server too
pip install "ai-quality-gate[server] @ git+https://github.com/sdkdeepa/ai-quality-gate@<commit-sha>#subdirectory=backend"
```

| Extra | Adds |
|---|---|
| (none) | the `aqg` CLI: pydantic, jsonschema, PyYAML |
| `server` | everything the API server needs to start: FastAPI, uvicorn, pydantic-settings, LangChain and Chroma (RAG demo), the OpenAI and Gemini SDKs, OpenTelemetry/Phoenix tracing |
| `ragas` | RAGAS judge metrics (includes `server`) |
| `deepeval` | DeepEval judge metrics (includes `server`) |
| `all` | all of the above |

Importing the server without its extra fails with a message naming the extra to
install. In a checkout, `uv sync` still installs everything (the dev group includes
`all`); `uv sync --no-dev` installs the core only. See [CHANGELOG.md](CHANGELOG.md).

## Use it in GitHub Actions

Add a `quality-gate.yml` to your repository (see [backend/aqg/config.py](backend/aqg/config.py)
for every setting), make your test runners write JUnit XML, and add a step after your tests:

```yaml
- name: Quality gate
  if: ${{ !cancelled() }}            # decide even when a test step failed
  uses: sdkdeepa/ai-quality-gate@v1
  with:
    config: quality-gate.yml         # the default
```

To pin an exact version, use the full commit SHA of a release instead of the tag:

```yaml
  uses: sdkdeepa/ai-quality-gate@<40-character commit sha> # v1.0.0
```

The action installs the `aqg` core from its own version (no server, database or AI model),
runs `aqg check`, uploads `report.json` and `summary.md` as a workflow artifact, writes the
run summary, and fails the step on BLOCK, on WARN when `fail_on_warn` is on, or on a config
or input error. It runs on Linux and macOS runners. Inputs: `config`, `working-directory`,
`version`, `commit`, `output`, `upload-report`, `artifact-name` (must be unique in a run),
`python-version`. Outputs: `decision`, `exit-code`, `report-dir`. This repository's own pull
requests are checked by this action (see `quality-gate.yml` at the root).

## Run locally

With Docker:

```bash
cp .env.example .env
docker compose up --build
```

Backend: `http://localhost:8000`  
Dashboard: `http://localhost:5173`

To stop: `docker compose down` (Ctrl+C alone, or closing the terminal, often
leaves the containers running in the background).

Evaluation runs are in-memory and reset with the backend process — useful
when testing locally and you want a clean slate. Restarting just the
backend is faster than a full teardown:

```bash
docker compose restart backend
```

If you do want a full stop/start cycle (e.g. to also pick up a code change
in `docker-compose.yml` or a Dockerfile):

```bash
docker compose down
docker compose up --build
```

Without Docker:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
uv run pytest -v
uv run ruff check .
```

```bash
cd frontend
npm install
npm run dev
npm test
npm run build
```

All supported environment variables and safe defaults are documented in [.env.example](.env.example). Real providers, model-based evaluators, authentication, and Phoenix tracing are opt-in.

## Sample evaluation

```bash
curl -X POST http://localhost:8000/api/v1/evaluations/runs \
  -H "Content-Type: application/json" \
  -d '{"dataset_name":"customer_support_bot","dataset_version":"1.1.0"}'
```

The bundled deterministic dataset contains 40 cases. Its fixture run intentionally includes failures so the gate can demonstrate critical-case and release-policy behavior. Run the gate with the returned run id:

```bash
curl -X POST http://localhost:8000/api/v1/gate/decisions \
  -H "Content-Type: application/json" \
  -d '{"run_id":"<run-id>"}'
```

A decision can be exported as JSON or HTML through `/api/v1/reports/{decision_id}/json` and `/html`.

![Sample HTML report](docs/images/sample-html-report.png)

## Testing and CI

The backend uses PyTest; the frontend uses Vitest and React Testing Library. Tests cover domain validation, datasets, provider contracts, evaluator adapters, RAG, policy decisions, reports, observability boundaries, API behavior, security/reliability paths, and the dashboard.

Every PR runs deterministic checks without paid model calls: lint/format, backend tests, API/integration tests, backward-compatibility tests, packaging checks (a core-only install, a full install, and an install from GitHub at the PR's commit), frontend tests, an end-to-end smoke test against a running service, Docker build validation, the quality gate on its own test results, a test of the GitHub Action, coverage, and dependency scans. The checks run once per pull request, not again after merging. A separate manual workflow can run a controlled live-provider evaluation using repository secrets and uploads reports as artifacts. See [docs/ci-cd.md](docs/ci-cd.md).

## Observability

When enabled, OpenTelemetry traces expose the run as nested spans for cases, provider calls, RAG retrieval/generation, and evaluator execution. Trace IDs are correlated with run and gate records. If Phoenix is unavailable, tracing degrades without changing release behavior. See [docs/debugging-failed-runs.md](docs/debugging-failed-runs.md).

## Production gaps and trade-offs

The project intentionally stops short of claiming production deployment. Current limitations include:

- Datasets, evaluation runs, and case results are in memory; policies, baselines, and gate decisions use SQLite.
- Write access can be protected by one shared API key, not per-user RBAC.
- TLS termination, rate limiting, and a production identity/audit system are outside this repository.
- Request-size enforcement relies on `Content-Length`, so chunked transfer is a known gap.
- Evaluator timeouts stop the caller from waiting but cannot forcibly kill an already-running Python thread.
- Evaluation is synchronous; higher scale would require durable storage, async job execution, connection pooling, and horizontal scaling.

See [SECURITY.md](SECURITY.md) for the security boundary and [DECISIONS.md](DECISIONS.md) for the major architectural trade-offs.

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design, data flow, decision flow, technology choices
- [EVALUATION_STRATEGY.md](EVALUATION_STRATEGY.md) — evaluator responsibilities, failure semantics, baselines, release policy
- [SECURITY.md](SECURITY.md) — implemented controls and known limitations
- [docs/ci-cd.md](docs/ci-cd.md) — deterministic and live CI workflows
- [docs/debugging-failed-runs.md](docs/debugging-failed-runs.md) — trace-based debugging
- [PROJECT_STATE.md](PROJECT_STATE.md) — concise current-state handoff
- [DECISIONS.md](DECISIONS.md) — architectural decision record

## License
MIT. See [LICENSE](LICENSE).
