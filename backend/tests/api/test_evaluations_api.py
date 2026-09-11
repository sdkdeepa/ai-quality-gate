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


def test_get_evaluation_run_exposes_metrics_grouped_by_framework(client):
    """Sprint 5 requirement #8. RAGAS is disabled by default in this test
    environment, so every case's grouping has only a 'deterministic' key -
    proves the grouping is present and correctly keyed without needing a
    live RAGAS evaluator."""
    run_response = client.post(
        "/api/v1/evaluations/runs",
        json={"dataset_name": "customer_support_bot", "dataset_version": "1.1.0"},
    )
    run_id = run_response.json()["run"]["id"]

    response = client.get(f"/api/v1/evaluations/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert "metrics_by_framework" in body
    assert set(body["metrics_by_framework"].keys()) == {c["case_id"] for c in body["case_results"]}
    rag_case_grouping = body["metrics_by_framework"]["rag-001"]
    assert set(rag_case_grouping.keys()) == {"deterministic"}


def test_get_evaluation_run_unknown_id_returns_404(client):
    response = client.get("/api/v1/evaluations/runs/does-not-exist")

    assert response.status_code == 404


def test_run_evaluation_with_frameworks_filter_restricts_metric_results(client):
    """Sprint 6 requirement #4: API-based evaluator-combination selection."""
    run_response = client.post(
        "/api/v1/evaluations/runs",
        json={
            "dataset_name": "customer_support_bot",
            "dataset_version": "1.1.0",
            "frameworks": ["deterministic"],
        },
    )
    run_id = run_response.json()["run"]["id"]

    response = client.get(f"/api/v1/evaluations/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    for case_grouping in body["metrics_by_framework"].values():
        assert set(case_grouping.keys()) <= {"deterministic"}


def test_run_evaluation_with_disabled_framework_yields_no_error_and_no_results_from_it(client):
    """Requesting a framework that isn't enabled process-wide (e.g.
    "deepeval" with AQG_DEEPEVAL_ENABLED unset in this test environment) is
    not an error - it just contributes zero evaluators/metric results."""
    response = client.post(
        "/api/v1/evaluations/runs",
        json={
            "dataset_name": "customer_support_bot",
            "dataset_version": "1.1.0",
            "frameworks": ["deepeval"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    # No deepeval evaluators exist in this process -> nothing to grade ->
    # every case vacuously passes, same rule as an empty metric_results list.
    assert body["passed_count"] == body["case_count"]


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
