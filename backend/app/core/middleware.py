import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.context import set_request_id

logger = logging.getLogger("app.request")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attaches a request/trace ID to every request, propagating an inbound header if present."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER, str(uuid.uuid4()))
        set_request_id(request_id)
        request.state.request_id = request_id

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request completed",
            extra={
                "path": request.url.path,
                "method": request.method,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Rejects a request whose declared body size exceeds
    `AQG_MAX_REQUEST_BODY_BYTES` with 413, before any handler reads it
    (Sprint 12 requirement: "request size limits").

    Checked via the `Content-Length` header rather than by streaming and
    counting the body as it arrives: every request this app expects to
    receive (JSON bodies to the evaluations/gate/rag endpoints) is sent
    with a Content-Length by every normal HTTP client (browsers, `curl`,
    `httpx`, `requests`, ...), so this catches the realistic case cheaply,
    with no buffering. A client deliberately using chunked transfer
    encoding to omit Content-Length could still stream an oversized body
    past this check — see DECISIONS.md's Sprint 12 entry for why that gap
    was accepted rather than closed with a streaming byte-counter this
    sprint (this API has no endpoint that intentionally accepts chunked
    uploads, so the realistic exposure is low, and Starlette/uvicorn's own
    default line-length/header limits already bound the worst case).
    """

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        super().__init__(app)
        self._max_body_bytes = max_body_bytes

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = None
            if declared_size is not None and declared_size > self._max_body_bytes:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "request_too_large",
                            "message": (
                                f"request body of {declared_size} bytes exceeds the "
                                f"{self._max_body_bytes}-byte limit"
                            ),
                        }
                    },
                )
        return await call_next(request)
