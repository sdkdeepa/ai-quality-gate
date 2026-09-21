def _run_and_decide(client):
    run_response = client.post(
        "/api/v1/evaluations/runs",
        json={"dataset_name": "customer_support_bot", "dataset_version": "1.0.0"},
    )
    run_id = run_response.json()["run"]["id"]
    decide_response = client.post("/api/v1/gate/decisions", json={"run_id": run_id})
    return run_id, decide_response.json()["id"]


def test_get_report_json_returns_downloadable_attachment(client):
    run_id, decision_id = _run_and_decide(client)

    response = client.get(f"/api/v1/reports/{decision_id}/json")

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert run_id in response.headers["content-disposition"]
    body = response.json()
    assert body["run_id"] == run_id
    assert body["decision_id"] == decision_id
    assert len(body["case_results"]) == 22


def test_get_report_json_includes_every_required_field(client):
    _, decision_id = _run_and_decide(client)

    response = client.get(f"/api/v1/reports/{decision_id}/json")

    body = response.json()
    for field in [
        "status",
        "run_id",
        "dataset_version",
        "provider",
        "model",
        "policy_version",
        "aggregate_metrics",
        "case_results",
        "critical_failures",
        "regression_summary",
        "mean_latency_ms",
        "total_input_tokens",
        "total_output_tokens",
        "total_estimated_cost",
        "framework_errors",
        "trace_id",
    ]:
        assert field in body, f"missing field: {field}"


def test_get_report_json_unknown_decision_returns_404(client):
    response = client.get("/api/v1/reports/does-not-exist/json")

    assert response.status_code == 404


def test_get_report_html_returns_downloadable_attachment(client):
    run_id, decision_id = _run_and_decide(client)

    response = client.get(f"/api/v1/reports/{decision_id}/html")

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "text/html" in response.headers["content-type"]
    assert run_id in response.text


def test_get_report_html_unknown_decision_returns_404(client):
    response = client.get("/api/v1/reports/does-not-exist/html")

    assert response.status_code == 404
