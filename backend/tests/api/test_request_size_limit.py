"""Uses real env vars + `get_settings.cache_clear()` — same convention as
`tests/unit/test_auth.py` — since `Settings` (and therefore
`max_request_body_bytes`) is process-cached via `@lru_cache`.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def tiny_limit_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("AQG_MAX_REQUEST_BODY_BYTES", "100")
    return TestClient(create_app())


class TestMaxBodySizeMiddleware:
    def test_a_request_declaring_a_body_larger_than_the_limit_is_rejected(self, tiny_limit_client):
        oversized_body = {"dataset_name": "x" * 500, "dataset_version": "1.0.0"}

        response = tiny_limit_client.post("/api/v1/evaluations/runs", json=oversized_body)

        assert response.status_code == 413
        assert response.json()["error"]["code"] == "request_too_large"

    def test_a_request_within_the_limit_is_not_rejected_for_size(self, tiny_limit_client):
        response = tiny_limit_client.post(
            "/api/v1/evaluations/runs",
            json={"dataset_name": "x", "dataset_version": "1.0.0"},
        )

        # Not necessarily 200 (the tiny dataset name won't resolve to a
        # real dataset) - the point is it must not be rejected for SIZE.
        assert response.status_code != 413

    def test_default_limit_comfortably_allows_a_normal_evaluation_request(self, client):
        """The default `client` fixture uses the real default limit
        (2MB) - an ordinary request must never be affected by it."""
        response = client.post(
            "/api/v1/evaluations/runs",
            json={"dataset_name": "customer_support_bot", "dataset_version": "1.0.0"},
        )

        assert response.status_code == 200

    def test_an_oversized_request_still_gets_a_request_id(self, tiny_limit_client):
        """The size-limit rejection must still be fully observable - see
        main.py's middleware-ordering comment: RequestIDMiddleware wraps
        this middleware, so even a 413 gets tagged and logged normally."""
        response = tiny_limit_client.post(
            "/api/v1/evaluations/runs",
            json={"dataset_name": "x" * 500, "dataset_version": "1.0.0"},
        )

        assert "X-Request-ID" in response.headers
