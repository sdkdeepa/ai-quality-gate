"""M0 compatibility: SQLite persistence across restarts, locked in.

Uses a real database file (AQG_POLICY_DB_PATH) and two separate app instances
to stand for a server restart. Checks what survives (policies, baselines, gate
decisions) and what does not (evaluation runs live in memory), exactly as the
gate behaves today.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from tests.compat._snapshot import assert_snapshot, normalize

DATASET = "customer_support_bot"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    path = tmp_path / "quality_gate.db"
    for name in (
        "AQG_RAGAS_ENABLED",
        "AQG_DEEPEVAL_ENABLED",
        "AQG_OPENAI_EVALS_ENABLED",
        "AQG_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AQG_POLICY_DB_PATH", str(path))
    get_settings.cache_clear()
    yield path
    get_settings.cache_clear()


def _start() -> TestClient:
    """A fresh app process reading the same database file."""
    get_settings.cache_clear()
    return TestClient(create_app())


def _run(client: TestClient, version: str) -> str:
    response = client.post(
        "/api/v1/evaluations/runs", json={"dataset_name": DATASET, "dataset_version": version}
    )
    assert response.status_code == 200
    return response.json()["run"]["id"]


def test_policies_baselines_and_decisions_survive_a_restart(db_path):
    first = _start()
    policy = first.post(
        "/api/v1/gate/policies",
        json={"name": "persisted", "version": "1.0.0", "min_pass_rate": 0.5},
    ).json()
    run_id = _run(first, "1.1.0")
    first.post("/api/v1/gate/baselines", json={"run_id": run_id, "approved_by": "compat"})
    decision = first.post("/api/v1/gate/decisions", json={"run_id": run_id}).json()
    assert db_path.exists()

    second = _start()
    active = second.get("/api/v1/gate/policies/active").json()
    policies = second.get("/api/v1/gate/policies").json()
    baselines = second.get("/api/v1/gate/baselines", params={"dataset_name": DATASET}).json()
    decisions = second.get("/api/v1/gate/decisions").json()
    old_decision = second.get(f"/api/v1/gate/decisions/{decision['id']}")
    old_run = second.get(f"/api/v1/evaluations/runs/{run_id}")
    old_report = second.get(f"/api/v1/reports/{decision['id']}/json")

    assert active["id"] == policy["id"]  # the custom policy stays active
    assert [p["name"] for p in policies].count("default") == 1  # default not seeded twice
    assert_snapshot(
        "db_after_restart",
        {
            "active_policy": normalize(active),
            "policy_names": sorted(p["name"] for p in policies),
            "baseline_versions": [b["version"] for b in baselines],
            "decision_count": len(decisions),
            "old_decision_status": old_decision.status_code,
            "old_decision": normalize(old_decision.json()),
            # Runs are kept in memory, so they are gone after a restart.
            "old_run_status": old_run.status_code,
            "old_report_status": old_report.status_code,
        },
    )


def test_baseline_versions_keep_counting_across_restarts(db_path):
    versions = []
    for _ in range(3):
        client = _start()
        baseline = client.post(
            "/api/v1/gate/baselines", json={"run_id": _run(client, "1.0.0")}
        ).json()
        versions.append(baseline["version"])
    latest_decision = client.post(
        "/api/v1/gate/decisions", json={"run_id": _run(client, "1.0.0")}
    ).json()
    assert versions == [1, 2, 3]
    assert latest_decision["baseline_version"] == 3
