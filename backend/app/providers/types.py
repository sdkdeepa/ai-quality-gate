from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ProviderErrorType(StrEnum):
    """Normalized failure categories every provider must map its own SDK's exceptions onto."""

    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    MALFORMED_RESPONSE = "malformed_response"
    AUTHENTICATION = "authentication"


class ProviderError(BaseModel):
    """Normalized error metadata. Providers never raise for expected failure modes —
    they return a ProviderResponse with this set instead, so a single case failing
    to reach a provider never crashes an entire evaluation run.
    """

    error_type: ProviderErrorType
    message: str
    retryable: bool = False


class ProviderRequest(BaseModel):
    """What the runner asks a provider to do for one case, independent of any SDK's shape."""

    case_id: str = Field(min_length=1)
    prompt: str
    system_prompt: str | None = None
    json_schema: dict[str, Any] | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None


class ProviderResponse(BaseModel):
    """The provider contract: the one normalized shape every provider returns.

    Every field a provider might not know (tokens, cost, request id) is optional
    rather than defaulted to a fake value, so callers can tell "zero" from "unknown".
    `error` is set instead of raising for the normalized ProviderErrorType failure
    modes; on error, the other fields carry whatever partial info is available
    (e.g. latency measured before the failure).
    """

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    text: str = ""
    structured_output: Any | None = None
    retrieved_context: list[str] = Field(default_factory=list)
    latency_ms: float = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    estimated_cost: float | None = Field(default=None, ge=0)
    request_id: str | None = None
    error: ProviderError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
