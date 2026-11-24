# CI/CD: deterministic vs. live evaluation, secrets, and cost controls

This is a task-oriented companion to `PROJECT_STATE.md`'s Sprint 11
section and `DECISIONS.md`'s Sprint 11 entries — start there for the
architecture and *why*; start here for the *how* of running/configuring
these workflows.

## Two workflows, two very different risk profiles

| | `.github/workflows/pr.yml` | `.github/workflows/live-eval.yml` |
|---|---|---|
| Trigger | every PR + push to `main` + manual | **manual only** (`workflow_dispatch`) |
| Provider | `deterministic` (fixture-replay) only | a real provider (`openai`/`gemini`) you pick |
| Needs secrets? | **no** | **yes** — `AQG_OPENAI_API_KEY` and/or `AQG_GEMINI_API_KEY` |
| Costs money? | **never** | **yes**, one real LLM call per case per run |
| Runs automatically? | yes | **never** — a human has to press the button |

The split exists specifically so a fork PR, a typo'd commit, or a bot
opening ten PRs a day can never rack up API costs or need a maintainer's
credentials — see Sprint 11's explicit requirement: "Do NOT require paid
model APIs for every PR."

## Deterministic CI (`pr.yml`) — runs on every PR, free

Thirteen jobs: Sprint 11's seven, the backward-compatibility job (M0), three packaging jobs (M7),
and two for the GitHub Action (M8):

1. **Lint & formatting** — `ruff check`/`ruff format --check` (backend),
   `oxlint`/`tsc -b` (frontend).
2. **Backend unit tests** — everything under `tests/` except `tests/api/` and `tests/compat/`
   (domain models, every evaluator framework — mocked, no network call —
   the Policy Engine, repositories, RAG pipeline, observability).
3. **Backend API/integration tests** — `tests/api/`, which drives the
   whole app through FastAPI's `TestClient` (real request/response cycle,
   every router and dependency wired up).
4. **Frontend tests** — Vitest + React Testing Library, then a production
   build (`npm run build`) to also catch type errors the tests alone
   wouldn't.
5. **Deterministic Quality Gate smoke suite** — `scripts/smoke_test.sh`
   run against a real, running `uvicorn` process (not `TestClient`):
   health check → run an evaluation → confirm it's listed → run the gate
   → download both report formats. This is the one job that exercises the
   *actual deployed shape* of the app rather than pytest's in-process
   client.
6. **Docker build validation** — builds both images, waits for the backend's
   health check and checks readiness (`/ready`), checks the
   backward-compatibility API contract against the built **backend
   container**, replaces the container (same data volume) to confirm
   policies and baselines survive, then runs the exact
   same `scripts/smoke_test.sh` against the built **backend container**
   (not just `uv run`), and separately confirms the **frontend container**
   serves its static assets and that `docker-entrypoint.sh` correctly
   wrote the injected `API_BASE_URL` into `env-config.js`.
7. **Backward compatibility** — `tests/compat/` (see "Backward
   compatibility" below): snapshots of today's gate decisions, evaluator
   results, API contract, write-access rules and SQLite persistence.
8. **Core-only install** — installs `backend/` into a fresh environment with no
   extras, confirms that FastAPI, LangChain, Chroma, RAGAS, DeepEval,
   OpenTelemetry/Phoenix and the AI SDKs are *not* installed, runs the `aqg`
   tests, runs `aqg check` on the JUnit fixtures (expects BLOCK, exit 1), and
   checks that importing the server prints which extra to install.
9. **Full install** — installs `backend[all]` into a fresh environment (held to
   the versions in `uv.lock`) and runs the full test suite plus every M0
   compatibility test.
10. **Install from GitHub** — `pip install "ai-quality-gate @
    git+https://github.com/<repo>@<the PR's commit>#subdirectory=backend"` into
    a fresh environment, then `aqg validate` and `aqg check` on a fixture.
11. **Quality gate (self-check)** — the backend unit, API and compatibility jobs
    write JUnit XML (the live-model `smoke` tests are left out with
    `-m "not smoke"`); this job runs the repository's own action (`uses: ./`)
    on it with the root `quality-gate.yml`. Compatibility tests are required, and
    each input has a `min_checks` floor. It runs even when a test job failed, so
    the run summary shows the gate's decision.
12. **GitHub Action test** — runs the action on the M2 JUnit fixtures: with the
    default policy it must BLOCK and fail its step; with a lenient policy it must
    PASS, and the `version` input must reach the report.
13. **Coverage** — backend (`pytest-cov`) and frontend
   (`@vitest/coverage-v8`) reports are uploaded as workflow artifacts and
   summarized in the job summary. No hard threshold is enforced yet (see
   "Known limitations" below).

**When it runs.** On every pull request (and by hand from the Actions tab), but
not again on the push to `main` after a merge: `main`'s branch protection has
"Require branches to be up to date before merging" turned on, so the PR run
already tested exactly what lands.

**Keeping it fast.** Lint runs ruff alone, at the version in `uv.lock`. The
backend jobs set up their environment with `.github/actions/backend-env`, which
installs the locked packages with `uv pip install` (every hash checked, as
`uv sync --frozen` does) instead of `uv sync`, then sets `UV_NO_SYNC=1` so the
existing `uv run …` commands use it as is. The Docker job starts at once and
reuses layers from earlier runs through the GitHub Actions cache.

None of these jobs reference `secrets.AQG_OPENAI_API_KEY` or
`secrets.AQG_GEMINI_API_KEY` anywhere — grep the file if you want to
confirm that yourself before trusting it.

### Running it yourself, locally, before pushing

Since M7 the server's packages are optional extras. `uv sync` in `backend/`
still installs everything (the dev group includes the `all` extra), and the
backend CI jobs install every extra (see "Keeping it fast" above). The Docker image
uses `uv sync --no-dev --extra all`.

```bash
cd backend
uv sync
uv run ruff check . && uv run ruff format --check .
uv run pytest -q tests --ignore=tests/api --ignore=tests/compat --cov=app --cov-report=term-missing
uv run pytest -q tests/api --cov=app --cov-report=term-missing

cd ../frontend
npm run lint && npx tsc -b
npm run test:coverage
npm run build

# the smoke suite, against a real running instance:
cd ../backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 &
bash ../scripts/smoke_test.sh http://127.0.0.1:8000
kill %1

# backward-compatibility snapshots:
uv run pytest -q tests/compat
# the same API contract check against a running server or container:
AQG_COMPAT_BASE_URL=http://127.0.0.1:8000 uv run pytest -q tests/compat/test_api_contract.py
# a core-only install, as the Core-only install job does:
cd ..
uv venv /tmp/aqg-core && uv pip install --python /tmp/aqg-core/bin/python ./backend
/tmp/aqg-core/bin/aqg --version
(cd backend && uv pip install --python /tmp/aqg-core/bin/python pytest \
  && /tmp/aqg-core/bin/python -m pytest -q tests/aqg --confcutdir=tests/aqg)
cd backend
# Docker build validation (requires Docker installed locally):
cd ..
docker build -t ai-quality-gate-backend:local ./backend
docker build -t ai-quality-gate-frontend:local ./frontend
```

## Backward compatibility

`backend/tests/compat/` locks in how the gate behaves today, so later changes
(the reusable framework work) can prove they changed nothing:

- `test_gate_snapshots.py`: every case's metric results for both bundled
  dataset versions, and gate decisions under the default policy, a custom
  policy that uses every setting, and an approved baseline, plus the run
  comparison and JSON report.
- `test_api_contract.py`: every route's status code and response shape
  (keys and types, not values) through a normal workflow and the main error
  cases, the list of routes, and the write-access (`AQG_API_KEY`) rules.
- `test_database_workflows.py`: what survives a restart when SQLite uses a
  real file (policies, baselines, gate decisions) and what doesn't
  (evaluation runs are in memory); baseline versions keep counting up.
- `scripts/compat_restart_check.sh`: the same persistence check against a
  running server or container, used by the Docker job.

Snapshots are in `backend/tests/compat/snapshots/`. Ids, timestamps and other
per-run values are masked; floats are rounded to 9 places. A missing snapshot
fails the test instead of being created. If a change is **meant** to alter
behavior, update the snapshots and explain why in the PR:

```bash
UPDATE_SNAPSHOTS=1 uv run pytest -q tests/compat
```

## Live evaluation (`live-eval.yml`) — manual only, costs money

### Triggering it

GitHub UI: **Actions → Live Evaluation (manual) → Run workflow**, then
fill in:
- `provider`: `openai` or `gemini`
- `dataset_name` / `dataset_version`: which golden dataset to run
- `policy_id`: optional — leave blank to gate against whatever policy is
  currently active

Or via the CLI: `gh workflow run live-eval.yml -f provider=openai -f
dataset_name=customer_support_bot -f dataset_version=1.1.0`.

### What it does

1. Validates the matching secret is actually set (fails fast with a clear
   error otherwise, before spending anything).
2. Starts the API with that provider's real key.
3. Runs the golden dataset through the live provider.
4. Runs the gate against the result.
5. **Clearly shows PASS/WARN/BLOCK** — as a GitHub Actions annotation
   (`::notice`/`::warning`/`::error`, visible directly on the workflow run
   without opening logs) and as a full job summary with the decision's
   reasons.
6. Downloads both the JSON and HTML report and **uploads them as workflow
   artifacts** (30-day retention).
7. **Fails the job if the decision was BLOCK** — deliberately the very
   last step, so every report/artifact step above still completes even on
   a BLOCK; only the overall pass/fail signal turns red.

### Setting up secrets

Repository → **Settings → Secrets and variables → Actions → New
repository secret**:
- `AQG_OPENAI_API_KEY` — required if you'll ever run with `provider: openai`
- `AQG_GEMINI_API_KEY` — required if you'll ever run with `provider: gemini`

Neither is required to exist for `pr.yml` to work — they're only read
inside `live-eval.yml`'s job, which only runs when manually triggered.

### Cost controls

- **Manual trigger only** — the single biggest control. No automation
  (PR, push, schedule, or another workflow) can ever start this one.
- **No judge frameworks enabled** — RAGAS/DeepEval/OpenAI-Evals-concept
  evaluators are NOT turned on for this workflow; only the deterministic
  evaluators grade the live provider's answers. Each of those frameworks
  is an *additional* LLM call per metric per case — leaving them off
  keeps a live run's cost to "one generation call per case," not "one
  generation call plus N judge calls per case." Enable them yourself for
  a specific investigation by editing the workflow's env block, with eyes
  open about the multiplier.
- **Pinned, cheap models** — `gpt-4o-mini` / `gemini-2.5-flash`, the same
  defaults `Settings` already uses, not a larger/pricier model.
- **A named, bounded dataset** — you choose exactly which dataset/version
  runs; there's no "run everything" mode. Keep a small dataset around
  (or a subset) specifically for this workflow if you want a tighter cost
  ceiling than the full golden set.
- **Reports uploaded regardless of outcome** — so a BLOCK still gives you
  the full picture (via artifacts) without needing to re-run and pay
  twice to see what happened.

## Known limitations (Sprint 11)

- **No coverage threshold is enforced** — the `coverage` job in `pr.yml`
  reports and uploads coverage but doesn't fail a PR for a regression.
  Backend was ~98% and frontend ~90% at the time this was written; a
  ratchet (never-go-below-current) or a fixed threshold is a reasonable
  follow-up once there's a baseline worth protecting.
- **Docker images aren't published anywhere** — `docker-build` in `pr.yml`
  builds and smoke-tests both images but doesn't push them to a registry;
  there's no release/tagging workflow yet.
- **The live workflow evaluates one dataset per run** — there's no matrix
  across multiple datasets/providers in a single trigger; run it again
  with different inputs if you need more than one combination.
