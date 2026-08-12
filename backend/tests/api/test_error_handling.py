from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import AppError, NotFoundError, register_exception_handlers
from app.core.middleware import RequestIDMiddleware


def _app_with_route(exc: Exception) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)

    @app.get("/boom")
    def boom():
        raise exc

    return app


def test_app_error_returns_structured_body():
    client = TestClient(_app_with_route(AppError("bad input", code="bad_input")))

    response = client.get("/boom")

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "bad_input"
    assert body["error"]["message"] == "bad input"
    assert body["error"]["request_id"]


def test_not_found_error_returns_404():
    client = TestClient(_app_with_route(NotFoundError("case not found")))

    response = client.get("/boom")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_unhandled_exception_returns_500_without_leaking_details():
    client = TestClient(
        _app_with_route(RuntimeError("secret internals")), raise_server_exceptions=False
    )

    response = client.get("/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "secret internals" not in response.text
