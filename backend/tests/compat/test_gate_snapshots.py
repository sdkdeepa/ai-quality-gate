"""M0 compatibility: the gate's decisions and evaluator results, locked in.

Runs the bundled deterministic datasets through the real app (in-process, no
network, no model calls) and compares the results with saved snapshots:

- every case's metric results for customer_support_bot 1.0.0 and 1.1.0
- gate decisions under the seeded default policy
- a decision compared against an approved baseline (regression summary)
- a decision under a custom policy that uses every policy setting
- the run comparison endpoint and the JSON report

If one of these fails, existing AI Quality Gate behavior changed.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app
from tests.compat._snapshot import assert_snapshot, normalize

DATASET = "customer_support_bot"


@pytest.fixture
def client(monkeypatch) -> TestClient:
    # A fresh app with default settings (in-memory SQLite, no AI frameworks).
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


def _run(client: TestClient, version: str) -> str:
    response = client.post(
        "/api/v1/evaluations/runs", json={"dataset_name": DATASET, "dataset_version": version}
    )
    assert response.status_code == 200
    return response.json()["run"]["id"]


def _decide(client: TestClient, run_id: str, policy_id: str | None = None) -> dict:
    body = {"run_id": run_id} | ({"policy_id": policy_id} if policy_id else {})
    response = client.post("/api/v1/gate/decisions", json=body)
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
def test_case_results_unchanged(client, version):
    run_id = _run(client, version)
    detail = client.get(f"/api/v1/evaluations/runs/{run_id}").json()
    assert_snapshot(f"case_results_{version}", normalize(detail))


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
def test_default_policy_decision_unchanged(client, version):
    decision = _decide(client, _run(client, version))
    assert_snapshot(f"decision_default_{version}", normalize(decision))


def test_regression_against_approved_baseline_unchanged(client):
    baseline_run = _run(client, "1.1.0")
    baseline = client.post(
        "/api/v1/gate/baselines", json={"run_id": baseline_run, "approved_by": "compat"}
    ).json()
    decision = _decide(client, _run(client, "1.0.0"))
    report = client.get(f"/api/v1/reports/{decision['id']}/json").json()
    assert_snapshot("baseline_approved_1.1.0", normalize(baseline))
    assert_snapshot("decision_regression_1.0.0_vs_1.1.0", normalize(decision))
    assert_snapshot("report_regression_1.0.0_vs_1.1.0", normalize(report))


def test_custom_policy_decision_unchanged(client):
    policy = client.post(
        "/api/v1/gate/policies",
        json={
            "name": "compat-strict",
            "version": "2.0.0",
            "required_metrics": [
                {"metric_name": "exact_match", "min_score": 0.4},
                {"metric_name": "citation_presence", "min_score": 0.95, "on_missing": "warn"},
                {
                    "metric_name": "ragas_faithfulness",
                    "on_missing": "warn",
                    "on_infrastructure_failure": "warn",
                },
            ],
            "min_pass_rate": 0.6,
            "critical_case_action": "warn",
            "max_regression_tolerance": 0.05,
            "regression_action": "warn",
            "latency_budget_ms": 500,
            "latency_budget_action": "block",
            "cost_budget_usd": 0.001,
            "cost_budget_action": "warn",
        },
    ).json()
    client.post("/api/v1/gate/baselines", json={"run_id": _run(client, "1.0.0")})
    decision = _decide(client, _run(client, "1.1.0"), policy["id"])
    assert_snapshot("policy_compat_strict", normalize(policy))
    assert_snapshot("decision_custom_policy_1.1.0", normalize(decision))


def test_compare_runs_unchanged(client):
    a, b = _run(client, "1.0.0"), _run(client, "1.1.0")
    comparison = client.get("/api/v1/gate/compare", params={"run_id_a": a, "run_id_b": b}).json()
    assert_snapshot("compare_1.0.0_vs_1.1.0", normalize(comparison))
