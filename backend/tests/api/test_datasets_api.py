def test_list_datasets_includes_seed_dataset(client):
    response = client.get("/api/v1/datasets")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    entry = next(d for d in body if d["name"] == "customer_support_bot")
    assert entry["version"] == "1.0.0"
    assert entry["case_count"] == 22
    assert "description" in entry
    assert "created_at" in entry
    assert "cases" not in entry


def test_get_dataset_returns_full_case_list(client):
    response = client.get("/api/v1/datasets/customer_support_bot/1.0.0")

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "customer_support_bot"
    assert len(body["cases"]) == 22


def test_get_dataset_latest_resolves_to_newest_version(client):
    response = client.get("/api/v1/datasets/customer_support_bot/latest")

    assert response.status_code == 200
    assert response.json()["version"] == "1.0.0"


def test_get_dataset_unknown_name_returns_404(client):
    response = client.get("/api/v1/datasets/does-not-exist/1.0.0")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_get_dataset_unknown_version_returns_404(client):
    response = client.get("/api/v1/datasets/customer_support_bot/9.9.9")

    assert response.status_code == 404
