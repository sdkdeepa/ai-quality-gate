def _run_evaluation(client, dataset_version="1.0.0"):
    response = client.post(
        "/api/v1/evaluations/runs",
        json={"dataset_name": "customer_support_bot", "dataset_version": dataset_version},
    )
    assert response.status_code == 200
    return response.json()["run"]["id"]


def test_default_policy_is_seeded_and_active(client):
    response = client.get("/api/v1/gate/policies/active")

    assert response.status_code == 200
    assert response.json()["name"] == "default"


def test_create_policy_becomes_active(client):
    response = client.post(
        "/api/v1/gate/policies",
        json={"name": "strict", "version": "1.0.0", "min_pass_rate": 0.9},
    )

    assert response.status_code == 200
    policy_id = response.json()["id"]

    active = client.get("/api/v1/gate/policies/active")
    assert active.json()["id"] == policy_id
    assert active.json()["name"] == "strict"


def test_get_unknown_policy_returns_404(client):
    response = client.get("/api/v1/gate/policies/does-not-exist")

    assert response.status_code == 404


def test_list_policies_includes_seeded_default(client):
    response = client.get("/api/v1/gate/policies")

    assert response.status_code == 200
    names = {p["name"] for p in response.json()}
    assert "default" in names


def test_run_gate_against_default_policy_blocks_on_critical_failures(client):
    """customer_support_bot@1.0.0 has two known critical-case failures
    (str-002, neg-001, per test_evaluations_api.py); the seeded default
    policy's critical_case_action is "block"."""
    run_id = _run_evaluation(client)

    response = client.post("/api/v1/gate/decisions", json={"run_id": run_id})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "block"
    assert set(body["critical_failures"]) == {"str-002", "neg-001"}
    assert body["run_id"] == run_id


def test_run_gate_records_full_audit_trail(client):
    run_id = _run_evaluation(client)

    response = client.post("/api/v1/gate/decisions", json={"run_id": run_id})

    body = response.json()
    assert body["dataset_version"] == "1.0.0"
    assert body["provider"] == "deterministic"
    assert body["policy_id"]
    assert body["policy_version"]
    assert "reasons" in body
    assert "aggregate_metrics" in body
    assert "framework_errors" in body


def test_run_gate_unknown_run_returns_404(client):
    response = client.post("/api/v1/gate/decisions", json={"run_id": "does-not-exist"})

    assert response.status_code == 404


def test_run_gate_with_explicit_policy_id(client):
    policy_response = client.post(
        "/api/v1/gate/policies",
        json={
            "name": "lenient",
            "version": "1.0.0",
            "min_pass_rate": 0.0,
            "critical_case_action": "warn",
        },
    )
    policy_id = policy_response.json()["id"]
    run_id = _run_evaluation(client)

    response = client.post(
        "/api/v1/gate/decisions", json={"run_id": run_id, "policy_id": policy_id}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["policy_id"] == policy_id
    assert body["status"] == "warn"


def test_get_decision_returns_previously_created_decision(client):
    run_id = _run_evaluation(client)
    decide_response = client.post("/api/v1/gate/decisions", json={"run_id": run_id})
    decision_id = decide_response.json()["id"]

    response = client.get(f"/api/v1/gate/decisions/{decision_id}")

    assert response.status_code == 200
    assert response.json()["id"] == decision_id


def test_get_unknown_decision_returns_404(client):
    response = client.get("/api/v1/gate/decisions/does-not-exist")

    assert response.status_code == 404


def test_list_decisions_filters_by_run_id(client):
    run_id_a = _run_evaluation(client, dataset_version="1.0.0")
    run_id_b = _run_evaluation(client, dataset_version="1.1.0")
    client.post("/api/v1/gate/decisions", json={"run_id": run_id_a})
    client.post("/api/v1/gate/decisions", json={"run_id": run_id_b})

    response = client.get(f"/api/v1/gate/decisions?run_id={run_id_a}")

    assert response.status_code == 200
    decisions = response.json()
    assert len(decisions) == 1
    assert decisions[0]["run_id"] == run_id_a


def test_list_decisions_without_filter_returns_history(client):
    run_id = _run_evaluation(client)
    client.post("/api/v1/gate/decisions", json={"run_id": run_id})

    response = client.get("/api/v1/gate/decisions")

    assert response.status_code == 200
    assert len(response.json()) >= 1


def test_approve_baseline_from_a_run(client):
    run_id = _run_evaluation(client)

    response = client.post(
        "/api/v1/gate/baselines",
        json={"run_id": run_id, "approved_by": "deepa", "notes": "first approved baseline"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert body["dataset_name"] == "customer_support_bot"
    assert body["approved_by"] == "deepa"


def test_approve_baseline_unknown_run_returns_404(client):
    response = client.post("/api/v1/gate/baselines", json={"run_id": "does-not-exist"})

    assert response.status_code == 404


def test_approve_baseline_increments_version_per_dataset(client):
    run_id_a = _run_evaluation(client, dataset_version="1.0.0")
    run_id_b = _run_evaluation(client, dataset_version="1.1.0")

    first = client.post("/api/v1/gate/baselines", json={"run_id": run_id_a})
    second = client.post("/api/v1/gate/baselines", json={"run_id": run_id_b})

    assert first.json()["version"] == 1
    assert second.json()["version"] == 2


def test_list_baselines_filters_by_dataset_name(client):
    run_id = _run_evaluation(client)
    client.post("/api/v1/gate/baselines", json={"run_id": run_id})

    response = client.get("/api/v1/gate/baselines?dataset_name=customer_support_bot")

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_run_gate_compares_against_approved_baseline(client):
    run_id = _run_evaluation(client)
    client.post("/api/v1/gate/baselines", json={"run_id": run_id})

    # Running the gate again against the SAME run should show zero
    # regression versus the baseline it was itself approved from.
    response = client.post("/api/v1/gate/decisions", json={"run_id": run_id})

    body = response.json()
    assert body["baseline_version"] == 1
    assert body["regression_summary"] is not None
    assert body["regression_summary"]["pass_rate_delta"] == 0.0


def test_compare_runs_returns_metric_deltas(client):
    run_id_a = _run_evaluation(client, dataset_version="1.0.0")
    run_id_b = _run_evaluation(client, dataset_version="1.1.0")

    response = client.get(f"/api/v1/gate/compare?run_id_a={run_id_a}&run_id_b={run_id_b}")

    assert response.status_code == 200
    body = response.json()
    assert body["run_a"]["id"] == run_id_a
    assert body["run_b"]["id"] == run_id_b
    assert "pass_rate_a" in body
    assert "pass_rate_b" in body
    assert "metric_deltas" in body


def test_compare_runs_unknown_run_returns_404(client):
    run_id = _run_evaluation(client)

    response = client.get(f"/api/v1/gate/compare?run_id_a={run_id}&run_id_b=does-not-exist")

    assert response.status_code == 404
