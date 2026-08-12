def test_health_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_response_includes_request_id_header(client):
    response = client.get("/health")

    assert "X-Request-ID" in response.headers


def test_health_propagates_inbound_request_id(client):
    response = client.get("/health", headers={"X-Request-ID": "trace-123"})

    assert response.headers["X-Request-ID"] == "trace-123"
