def test_run_deterministic_evaluation_against_seed_dataset(client):
    response = client.post(
        "/api/v1/evaluations/runs",
        json={"dataset_name": "customer_support_bot", "dataset_version": "1.0.0"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["status"] == "completed"
    assert body["run"]["dataset_version"] == "1.0.0"
    assert body["case_count"] == 22
    assert body["passed_count"] == 15
    assert body["failed_count"] == 7
    assert set(body["critical_failure_case_ids"]) == {"str-002", "neg-001"}
    assert "case_results" not in body


def test_run_deterministic_evaluation_defaults_to_latest_version(client):
    response = client.post(
        "/api/v1/evaluations/runs", json={"dataset_name": "customer_support_bot"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["dataset_version"] == "1.1.0"
    assert body["case_count"] == 40
    assert body["passed_count"] == 31
    assert body["failed_count"] == 9


def test_run_deterministic_evaluation_against_v1_1_0_rag_cases(client):
    response = client.post(
        "/api/v1/evaluations/runs",
        json={"dataset_name": "customer_support_bot", "dataset_version": "1.1.0"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["case_count"] == 40
    assert body["passed_count"] == 31
    assert body["failed_count"] == 9
    assert set(body["critical_failure_case_ids"]) == {"str-002", "neg-001", "rag-013"}


def test_run_deterministic_evaluation_unknown_dataset_returns_404(client):
    response = client.post("/api/v1/evaluations/runs", json={"dataset_name": "does-not-exist"})

    assert response.status_code == 404


def test_get_evaluation_run_returns_case_results(client):
    run_response = client.post(
        "/api/v1/evaluations/runs",
        json={"dataset_name": "customer_support_bot", "dataset_version": "1.0.0"},
    )
    run_id = run_response.json()["run"]["id"]

    response = client.get(f"/api/v1/evaluations/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert len(body["case_results"]) == 22
    critical_case = next(c for c in body["case_results"] if c["case_id"] == "neg-001")
    assert critical_case["passed"] is False
    assert critical_case["critical_failure"] is True
    failing_metrics = {m["metric_name"] for m in critical_case["metric_results"] if not m["passed"]}
    assert "forbidden_phrases" in failing_metrics
    assert "expected_refusal" in failing_metrics


def test_get_evaluation_run_unknown_id_returns_404(client):
    response = client.get("/api/v1/evaluations/runs/does-not-exist")

    assert response.status_code == 404


def test_run_with_explicit_deterministic_provider_matches_default(client):
    response = client.post(
        "/api/v1/evaluations/runs",
        json={
            "dataset_name": "customer_support_bot",
            "dataset_version": "1.0.0",
            "provider": "deterministic",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["provider"] == "deterministic"
    assert body["passed_count"] == 15
    assert body["failed_count"] == 7


def test_run_with_openai_provider_without_api_key_returns_400(client):
    response = client.post(
        "/api/v1/evaluations/runs",
        json={
            "dataset_name": "customer_support_bot",
            "dataset_version": "1.0.0",
            "provider": "openai",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_not_configured"


def test_run_with_gemini_provider_without_api_key_returns_400(client):
    response = client.post(
        "/api/v1/evaluations/runs",
        json={
            "dataset_name": "customer_support_bot",
            "dataset_version": "1.0.0",
            "provider": "gemini",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_not_configured"


def test_run_with_unknown_provider_value_returns_422(client):
    response = client.post(
        "/api/v1/evaluations/runs",
        json={"dataset_name": "customer_support_bot", "provider": "not-a-real-provider"},
    )

    assert response.status_code == 422
