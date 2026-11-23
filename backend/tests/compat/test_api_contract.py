"""M0 compatibility: the HTTP API contract, locked in.

Walks every /api/v1 route (and /health, /ready) through a normal workflow plus
the main error cases, and compares each response's status code and JSON shape
(keys and value types, not values) with a saved snapshot.

Runs in-process by default. Set AQG_COMPAT_BASE_URL (for example
http://127.0.0.1:8000) to run the same checks against a running server or
Docker container. Live mode expects a freshly started server with default
settings and no API key.
"""

import os

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from tests.compat._snapshot import assert_snapshot, shape

DATASET = "customer_support_bot"
BASE_URL = os.environ.get("AQG_COMPAT_BASE_URL")


@pytest.fixture
def client(monkeypatch):
    if BASE_URL:
        with httpx.Client(base_url=BASE_URL, timeout=60) as live:
            yield live
        return
    for name in (
        "AQG_POLICY_DB_PATH",
        "AQG_RAGAS_ENABLED",
        "AQG_DEEPEVAL_ENABLED",
        "AQG_OPENAI_EVALS_ENABLED",
        "AQG_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield TestClient(create_app())
    get_settings.cache_clear()


def _record(results: dict, key: str, response) -> dict | list | None:
    content_type = response.headers.get("content-type", "").split(";")[0]
    entry = {"status": response.status_code, "content_type": content_type}
    body = None
    if content_type == "application/json":
        body = response.json()
        entry["shape"] = shape(body)
    else:
        entry["starts_with_html"] = (
            response.text.lstrip().lower().startswith(("<!doctype html", "<html"))
        )
    results[key] = entry
    return body


def test_api_contract(client):
    r: dict = {}

    # Health and status
    _record(r, "GET /health", client.get("/health"))
    _record(r, "GET /ready", client.get("/ready"))
    _record(r, "GET /api/v1/status", client.get("/api/v1/status"))

    # Datasets
    _record(r, "GET /api/v1/datasets", client.get("/api/v1/datasets"))
    _record(
        r, "GET /api/v1/datasets/{name}/{version}", client.get(f"/api/v1/datasets/{DATASET}/1.1.0")
    )
    _record(
        r, "GET /api/v1/datasets/{name}/latest", client.get(f"/api/v1/datasets/{DATASET}/latest")
    )
    _record(
        r,
        "GET /api/v1/datasets/{name}/{version} unknown",
        client.get(f"/api/v1/datasets/{DATASET}/9.9.9"),
    )

    # Evaluation runs
    run_a = _record(
        r,
        "POST /api/v1/evaluations/runs 1.0.0",
        client.post(
            "/api/v1/evaluations/runs", json={"dataset_name": DATASET, "dataset_version": "1.0.0"}
        ),
    )
    run_b = _record(
        r,
        "POST /api/v1/evaluations/runs 1.1.0",
        client.post(
            "/api/v1/evaluations/runs", json={"dataset_name": DATASET, "dataset_version": "1.1.0"}
        ),
    )
    _record(
        r,
        "POST /api/v1/evaluations/runs invalid body",
        client.post("/api/v1/evaluations/runs", json={}),
    )
    _record(
        r,
        "POST /api/v1/evaluations/runs unknown dataset",
        client.post(
            "/api/v1/evaluations/runs", json={"dataset_name": "nope", "dataset_version": "1.0.0"}
        ),
    )
    run_a_id, run_b_id = run_a["run"]["id"], run_b["run"]["id"]
    _record(r, "GET /api/v1/evaluations/runs", client.get("/api/v1/evaluations/runs"))
    _record(
        r,
        "GET /api/v1/evaluations/runs/{run_id}",
        client.get(f"/api/v1/evaluations/runs/{run_a_id}"),
    )
    _record(
        r,
        "GET /api/v1/evaluations/runs/{run_id} unknown",
        client.get("/api/v1/evaluations/runs/does-not-exist"),
    )

    # Policies
    _record(
        r,
        "GET /api/v1/gate/policies/active (seeded default)",
        client.get("/api/v1/gate/policies/active"),
    )
    policy = _record(
        r,
        "POST /api/v1/gate/policies",
        client.post(
            "/api/v1/gate/policies",
            json={"name": "contract", "version": "1.0.0", "min_pass_rate": 0.5},
        ),
    )
    _record(
        r,
        "POST /api/v1/gate/policies invalid body",
        client.post("/api/v1/gate/policies", json={"name": "x"}),
    )
    _record(r, "GET /api/v1/gate/policies", client.get("/api/v1/gate/policies"))
    _record(
        r,
        "GET /api/v1/gate/policies/{policy_id}",
        client.get(f"/api/v1/gate/policies/{policy['id']}"),
    )
    _record(
        r,
        "GET /api/v1/gate/policies/{policy_id} unknown",
        client.get("/api/v1/gate/policies/does-not-exist"),
    )
    _record(r, "GET /api/v1/gate/policies/active", client.get("/api/v1/gate/policies/active"))

    # Baselines, decisions, comparison
    _record(
        r,
        "POST /api/v1/gate/baselines",
        client.post("/api/v1/gate/baselines", json={"run_id": run_b_id, "approved_by": "contract"}),
    )
    _record(
        r,
        "POST /api/v1/gate/baselines unknown run",
        client.post("/api/v1/gate/baselines", json={"run_id": "does-not-exist"}),
    )
    _record(
        r,
        "GET /api/v1/gate/baselines",
        client.get("/api/v1/gate/baselines", params={"dataset_name": DATASET}),
    )
    decision = _record(
        r,
        "POST /api/v1/gate/decisions",
        client.post("/api/v1/gate/decisions", json={"run_id": run_a_id}),
    )
    _record(
        r,
        "POST /api/v1/gate/decisions unknown run",
        client.post("/api/v1/gate/decisions", json={"run_id": "does-not-exist"}),
    )
    _record(r, "GET /api/v1/gate/decisions", client.get("/api/v1/gate/decisions"))
    _record(
        r,
        "GET /api/v1/gate/decisions/{decision_id}",
        client.get(f"/api/v1/gate/decisions/{decision['id']}"),
    )
    _record(
        r,
        "GET /api/v1/gate/decisions/{decision_id} unknown",
        client.get("/api/v1/gate/decisions/does-not-exist"),
    )
    _record(
        r,
        "GET /api/v1/gate/compare",
        client.get("/api/v1/gate/compare", params={"run_id_a": run_a_id, "run_id_b": run_b_id}),
    )

    # Reports
    _record(
        r,
        "GET /api/v1/reports/{decision_id}/json",
        client.get(f"/api/v1/reports/{decision['id']}/json"),
    )
    _record(
        r,
        "GET /api/v1/reports/{decision_id}/html",
        client.get(f"/api/v1/reports/{decision['id']}/html"),
    )
    _record(
        r,
        "GET /api/v1/reports/{decision_id}/json unknown",
        client.get("/api/v1/reports/does-not-exist/json"),
    )

    # RAG (deterministic paths only: no model calls, no API keys)
    _record(r, "GET /api/v1/rag/chunks", client.get("/api/v1/rag/chunks"))
    _record(
        r,
        "GET /api/v1/rag/chunks?query",
        client.get("/api/v1/rag/chunks", params={"query": "electronics warranty length"}),
    )
    _record(
        r,
        "POST /api/v1/rag/query without provider",
        client.post("/api/v1/rag/query", json={"query": "What is the warranty length?"}),
    )
    _record(
        r,
        "POST /api/v1/rag/query openai without key",
        client.post(
            "/api/v1/rag/query",
            json={"query": "What is the warranty length?", "provider": "openai"},
        ),
    )
    _record(
        r,
        "POST /api/v1/rag/evaluate/{case_id}",
        client.post("/api/v1/rag/evaluate/rag-001", json={}),
    )

    assert_snapshot("api_contract", r)


def test_every_route_is_covered():
    """A route added or removed must show up here, so the contract is updated on purpose."""
    get_settings.cache_clear()
    app = create_app()
    # Read from the OpenAPI document: it lists every route the app serves,
    # however the routers are mounted.
    paths = app.openapi()["paths"]
    routes = sorted(
        f"{method.upper()} {path}" for path, methods in paths.items() for method in methods
    )
    assert_snapshot("api_routes", routes)


@pytest.mark.skipif(bool(BASE_URL), reason="needs to set AQG_API_KEY on the app; in-process only")
def test_write_access_contract(monkeypatch):
    """With AQG_API_KEY set, write routes need the X-API-Key header; reads stay open."""
    monkeypatch.setenv("AQG_API_KEY", "compat-key")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        body = {"dataset_name": DATASET, "dataset_version": "1.0.0"}
        results = {
            "POST without key": client.post("/api/v1/evaluations/runs", json=body).status_code,
            "POST wrong key": client.post(
                "/api/v1/evaluations/runs", json=body, headers={"X-API-Key": "nope"}
            ).status_code,
            "POST right key": client.post(
                "/api/v1/evaluations/runs", json=body, headers={"X-API-Key": "compat-key"}
            ).status_code,
            "GET without key": client.get("/api/v1/gate/policies/active").status_code,
        }
    finally:
        get_settings.cache_clear()
    assert_snapshot("api_write_access", results)
