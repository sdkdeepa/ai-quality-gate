"""Uses real env vars + `get_settings.cache_clear()` since `Settings` is
process-cached via `@lru_cache` - same convention as
`tests/evaluation/ragas/test_app_wiring.py` etc.: the cache is cleared
both before (so this test doesn't inherit a stale cached Settings from an
earlier test) and after (so later tests don't inherit this test's env).
"""

import pytest
from fastapi.testclient import TestClient

from app.core.auth import ApiKeyAuthBackend
from app.core.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def authed_client(monkeypatch) -> TestClient:
    """A client whose app has AQG_API_KEY configured - unlike the default
    `client` fixture (no key set, auth fully off)."""
    monkeypatch.setenv("AQG_API_KEY", "test-secret-key")
    app = create_app()
    return TestClient(app)


class TestApiKeyAuthBackend:
    def test_disabled_when_no_key_is_configured(self):
        backend = ApiKeyAuthBackend(None)

        assert backend.enabled is False
        assert backend.check_write_access(None) is True
        assert backend.check_write_access("anything") is True

    def test_enabled_requires_the_exact_key(self):
        backend = ApiKeyAuthBackend("correct-key")

        assert backend.enabled is True
        assert backend.check_write_access("correct-key") is True
        assert backend.check_write_access("wrong-key") is False
        assert backend.check_write_access(None) is False


class TestAuthDisabledByDefault:
    """The default `client` fixture never sets AQG_API_KEY - every
    existing test in the suite already relies on mutating endpoints
    working with no header at all, which is exactly the "opt-in,
    unconfigured install unaffected" behavior this asserts explicitly."""

    def test_running_an_evaluation_needs_no_api_key_when_none_is_configured(self, client):
        response = client.post(
            "/api/v1/evaluations/runs",
            json={"dataset_name": "customer_support_bot", "dataset_version": "1.0.0"},
        )

        assert response.status_code == 200


class TestAuthEnforcedWhenConfigured:
    def test_mutating_endpoint_rejects_a_request_with_no_key(self, authed_client):
        response = authed_client.post(
            "/api/v1/evaluations/runs",
            json={"dataset_name": "customer_support_bot", "dataset_version": "1.0.0"},
        )

        assert response.status_code == 401

    def test_mutating_endpoint_rejects_a_request_with_the_wrong_key(self, authed_client):
        response = authed_client.post(
            "/api/v1/evaluations/runs",
            json={"dataset_name": "customer_support_bot", "dataset_version": "1.0.0"},
            headers={"X-API-Key": "wrong-key"},
        )

        assert response.status_code == 401

    def test_mutating_endpoint_accepts_a_request_with_the_correct_key(self, authed_client):
        response = authed_client.post(
            "/api/v1/evaluations/runs",
            json={"dataset_name": "customer_support_bot", "dataset_version": "1.0.0"},
            headers={"X-API-Key": "test-secret-key"},
        )

        assert response.status_code == 200

    def test_read_only_endpoints_stay_open_with_no_key_even_when_auth_is_configured(
        self, authed_client
    ):
        response = authed_client.get("/api/v1/datasets")

        assert response.status_code == 200

    def test_gate_decisions_endpoint_is_gated_too(self, authed_client):
        run_response = authed_client.post(
            "/api/v1/evaluations/runs",
            json={"dataset_name": "customer_support_bot", "dataset_version": "1.0.0"},
            headers={"X-API-Key": "test-secret-key"},
        )
        run_id = run_response.json()["run"]["id"]

        unauthed = authed_client.post("/api/v1/gate/decisions", json={"run_id": run_id})
        authed = authed_client.post(
            "/api/v1/gate/decisions",
            json={"run_id": run_id},
            headers={"X-API-Key": "test-secret-key"},
        )

        assert unauthed.status_code == 401
        assert authed.status_code == 200
