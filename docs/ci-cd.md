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

Seven jobs, matching Sprint 11's own list:

1. **Lint & formatting** — `ruff check`/`ruff format --check` (backend),
   `oxlint`/`tsc -b` (frontend).
2. **Backend unit tests** — everything under `tests/` except `tests/api/`
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
6. **Docker build validation** — builds both images, then runs the exact
   same `scripts/smoke_test.sh` against the built **backend container**
   (not just `uv run`), and separately confirms the **frontend container**
   serves its static assets and that `docker-entrypoint.sh` correctly
   wrote the injected `API_BASE_URL` into `env-config.js`.
7. **Coverage** — backend (`pytest-cov`) and frontend
   (`@vitest/coverage-v8`) reports are uploaded as workflow artifacts and
   summarized in the job summary. No hard threshold is enforced yet (see
   "Known limitations" below).

None of these jobs reference `secrets.AQG_OPENAI_API_KEY` or
`secrets.AQG_GEMINI_API_KEY` anywhere — grep the file if you want to
confirm that yourself before trusting it.

### Running it yourself, locally, before pushing

```bash
cd backend
uv run ruff check . && uv run ruff format --check .
uv run pytest -q tests --ignore=tests/api --cov=app --cov-report=term-missing
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

# Docker build validation (requires Docker installed locally):
cd ..
docker build -t ai-quality-gate-backend:local ./backend
docker build -t ai-quality-gate-frontend:local ./frontend
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
