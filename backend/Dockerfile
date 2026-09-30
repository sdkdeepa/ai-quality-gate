# syntax=docker/dockerfile:1
#
# Multi-stage build for the AI Quality Gate backend.
#
# Stage 1 (builder) resolves dependencies with `uv` into a self-contained
# virtualenv. Stage 2 (runtime) copies only that venv plus the application
# code into a slim image — no compilers, no uv itself, no build-time
# dependency caches ship in the final image.
#
# No secrets are baked in anywhere: AQG_OPENAI_API_KEY / AQG_GEMINI_API_KEY
# / any other credential are read from the environment at container start
# (see docker-compose.yml's `environment:`/`env_file:`), never COPYed or
# ARGed into a layer. `.dockerignore` additionally excludes `.env*` so a
# stray `docker build .` from a directory with a real `.env` file can't
# accidentally pull one in via a wildcard COPY.

FROM python:3.12-slim AS builder

# Install uv by copying its published binary (no network call to a script,
# no pip-installing uv into the image we're about to discard anyway).
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy only the dependency manifests first so this layer is cached across
# rebuilds that only change application code, not dependencies.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Now copy the actual application and install it into the same venv.
COPY app ./app
COPY datasets ./datasets
COPY rag_corpus ./rag_corpus
COPY README.md ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

# Non-root user: the app never needs root inside the container (it only
# writes to its own SQLite/Chroma data directories, both under /app/data,
# which this user owns).
RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser --home-dir /app --shell /usr/sbin/nologin appuser

# curl is the only extra package: used by the HEALTHCHECK below to hit
# GET /health without needing a Python interpreter invocation per check.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/app /app/app
COPY --from=builder --chown=appuser:appuser /app/datasets /app/datasets
COPY --from=builder --chown=appuser:appuser /app/rag_corpus /app/rag_corpus

# Writable data directory for the SQLite policy/baseline/decision store
# (AQG_POLICY_DB_PATH) and the Chroma vector store (AQG_RAG_CHROMA_DIR) —
# both default to relative paths under the backend root, i.e. here.
RUN mkdir -p /app/data /app/chroma_store && chown -R appuser:appuser /app/data /app/chroma_store

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    AQG_POLICY_DB_PATH="data/quality_gate.db" \
    AQG_RAG_CHROMA_DIR="chroma_store"

USER appuser

EXPOSE 8000

# Liveness check: GET /health always returns 200 once the process is up
# (app/api/health.py) — no external dependency (DB, RAG store, provider
# API) is on this path, so a healthy container means "the process is
# serving," not "every downstream integration is reachable."
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
