def test_status_returns_expected_shape(client):
    response = client.get("/api/v1/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app_name"] == "AI Quality Gate"
    assert "version" in body
    assert "environment" in body
    assert body["uptime_seconds"] >= 0
    assert body["counts"] == {"evaluation_cases": 0, "evaluation_runs": 0}


def test_status_response_includes_request_id_header(client):
    response = client.get("/api/v1/status")

    assert "X-Request-ID" in response.headers
