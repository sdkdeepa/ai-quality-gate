"""Basic RBAC boundary for Sprint 12: a two-role model — anyone can read
(every GET stays open, no configuration needed), a single shared secret
gates every *mutating* endpoint (POST/PUT/DELETE). This is deliberately
not full per-user/per-role RBAC; it is the smallest real boundary that
distinguishes "can look" from "can change something," plus a documented
abstraction point (`AuthBackend`) a real identity system would implement
instead — see DECISIONS.md's Sprint 12 entry for why this scope was
judged sufficient for "a basic RBAC boundary or documented auth
abstraction" rather than building out real per-user roles this sprint.

Off by default (`AQG_API_KEY` unset): `require_write_access` becomes a
complete no-op, matching every other opt-in feature's "unconfigured
install is unaffected" convention in this codebase.
"""

from typing import Annotated, Protocol

from fastapi import Header, HTTPException, Request, status


class AuthBackend(Protocol):
    """What any auth backend must answer: given whatever credential the
    caller presented, may they perform a mutating operation? A real
    per-user/per-role system (a database of API keys mapped to
    permissions, JWT-based identity, ...) would implement this same
    Protocol — `require_write_access` below depends on `AuthBackend`,
    never on `ApiKeyAuthBackend` directly, so swapping the backend never
    requires touching a single router.
    """

    def check_write_access(self, credential: str | None) -> bool: ...


class ApiKeyAuthBackend:
    """The one concrete AuthBackend this sprint ships: a single shared
    secret (`AQG_API_KEY`), checked via the `X-API-Key` request header.
    Every valid holder of the key has full write access — there is no
    per-user identity or finer-grained permission here, which is exactly
    what makes this "basic" rather than real RBAC.
    """

    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    @property
    def enabled(self) -> bool:
        return self._api_key is not None

    def check_write_access(self, credential: str | None) -> bool:
        if not self.enabled:
            return True
        return credential is not None and credential == self._api_key


def require_write_access(
    request: Request,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """FastAPI dependency gating one mutating endpoint. Add
    `Depends(require_write_access)` to any POST/PUT/DELETE route.

    Reads the configured `AuthBackend` from `request.app.state.auth_backend`
    (built once at `create_app()` time, same pattern as every other
    service in `app/api/deps.py`) rather than importing `Settings`
    directly, so a future backend swap only ever touches `main.py`'s
    wiring, never this function or any router that depends on it.
    """
    backend: AuthBackend = request.app.state.auth_backend
    if not backend.check_write_access(x_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid API key",
        )
