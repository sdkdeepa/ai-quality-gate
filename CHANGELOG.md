# Changelog

All notable changes to this project. Versions follow [semantic versioning](https://semver.org/).

## Unreleased

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
- use this repository's workflows: they run `uv sync --extra all`.

The resolved packages and versions in `uv.lock` are the same as before the
split. API routes, the Policy Engine, the evaluators, SQLite storage, the
dashboard and the RAG demo are unchanged.

### Added

- `aqg` CLI (M1–M6): a quality-evidence model, a JUnit XML importer for
  pytest, Vitest and Playwright, an LLM-run adapter, an evidence policy,
  approved baselines with regression reports, and `aqg check`,
  `aqg baseline approve` and `aqg validate`.
- CI packaging checks (M7): a core-only install, a full install, and an install
  from GitHub at the PR's commit.
