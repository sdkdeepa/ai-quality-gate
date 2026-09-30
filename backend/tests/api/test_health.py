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


def test_ready_returns_200_when_every_dependency_is_reachable(client):
    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {
        "datasets": "ok",
        "policy_store": "ok",
        "rag_vector_store": "ok",
    }


def test_ready_returns_503_and_names_the_failing_check_when_a_dependency_is_broken(
    client, monkeypatch
):
    def _broken():
        raise RuntimeError("disk full")

    monkeypatch.setattr(client.app.state.policy_repository, "list", _broken)

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert "disk full" in body["checks"]["policy_store"]
    assert body["checks"]["datasets"] == "ok"
