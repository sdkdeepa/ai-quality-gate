# Changelog

All notable changes to this project. Versions follow [semantic versioning](https://semver.org/).

## Unreleased

### Changed: CI for this repository

- The Docker job builds its images with plain `docker build` again. The GitHub
  Actions layer cache added in 1.0.0 made the backend image build slower (1m48s
  against 52s), so it is gone. No change to the package, the CLI or the action.

## 1.0.0 (2026-11-23)

The first release of the `aqg` quality gate. Install it from GitHub (PyPI comes
later). Use the GitHub Action by tag or by commit SHA:

```yaml
- uses: sdkdeepa/ai-quality-gate@v1
# or, for teams that require full SHAs:
- uses: sdkdeepa/ai-quality-gate@<40-character commit sha> # v1.0.0
```

### Added

- `aqg` CLI (M1–M6): a quality-evidence model, a JUnit XML importer for
  pytest, Vitest and Playwright, an LLM-run adapter, an evidence policy,
  approved baselines with regression reports, and `aqg check`,
  `aqg baseline approve` and `aqg validate`.
- GitHub Action (`action.yml`, M8): installs the core from the action's own
  version, runs `aqg check`, uploads `report.json` and `summary.md` as an
  artifact, writes the run summary, and fails the step on BLOCK or an error.
  Every action it uses is pinned by commit SHA.
- The gate checks its own pull requests with its own action (M8).
- CI packaging checks (M7): a core-only install, a full install, and an install
  from GitHub at the PR's commit.

### Changed: installing without extras now gives the core only (M7)

The package's dependencies are split. A plain install now installs only the
`aqg` command-line gate and its core dependencies (pydantic, jsonschema,
PyYAML). The API server's packages moved to optional extras:

| Extra | Adds |
|---|---|
| `server` | everything the API server needs to start: FastAPI, uvicorn, pydantic-settings, LangChain and Chroma, the OpenAI and Gemini SDKs, OpenTelemetry/Phoenix |
| `ragas` | RAGAS judge metrics (includes `server`) |
| `deepeval` | DeepEval judge metrics (includes `server`) |
| `all` | all of the above |

**If you run the server**, install it with an extra:
`pip install "ai-quality-gate[server]"` (or `[all]` for the judge metrics too).
Importing the server without its packages now fails with a message that names
the extra to install.

**Nothing changes** if you:

- work in a checkout with `uv sync`: the dev group includes the `all` extra,
- use the Docker image: it installs `all`,
- use this repository's workflows: they install every extra.

The resolved packages and versions in `uv.lock` are the same as before the
split. API routes, the Policy Engine, the evaluators, SQLite storage, the
dashboard and the RAG demo are unchanged.

### Changed: faster CI for this repository

- PR Checks run once per change, on the pull request. The second, identical run
  on every push to `main` is gone; `main`'s branch protection requires branches
  to be up to date, so the PR run tests what lands.
- Lint runs ruff alone (at the version in `uv.lock`) instead of installing the
  whole backend; the Docker job starts at once and reuses layers from earlier
  runs; the backend jobs install the locked environment with `uv pip install`
  (hashes checked) instead of `uv sync`.
