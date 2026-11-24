# AI Quality Gate

Decides PASS, WARN or BLOCK for a release from its test evidence.

This package has two parts:

- **`aqg`, the command-line gate (the core).** It reads JUnit XML from pytest,
  Vitest and Playwright, applies the policy in `quality-gate.yml`, compares the
  run with an approved baseline, and writes `report.json` and `summary.md`. Its
  only dependencies are pydantic, jsonschema and PyYAML: no server, database or
  AI model.
- **The API server (the `server` extra).** FastAPI service that evaluates
  LLM/RAG applications before release and returns PASS / WARN / BLOCK decisions,
  with the dashboard backend, RAG demo and model-based evaluators.

```bash
# The CLI only (the package lives in backend/ of the repository)
pip install "ai-quality-gate @ git+https://github.com/sdkdeepa/ai-quality-gate@<commit-sha>#subdirectory=backend"
aqg validate                 # check quality-gate.yml
aqg check                    # decide; exit 0 pass, 1 block, 2 config error, 3 input error

# The server too
pip install "ai-quality-gate[server] @ git+https://github.com/sdkdeepa/ai-quality-gate@<commit-sha>#subdirectory=backend"
```

Extras: `server`, `ragas`, `deepeval`, `all`. See the repository root `README.md`
for the details, and `PROJECT_STATE.md` for the server's architecture and run
instructions.
