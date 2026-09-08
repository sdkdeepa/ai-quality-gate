from typing import Protocol

from app.providers.types import ProviderRequest, ProviderResponse


class Provider(Protocol):
    """A system-under-test response source.

    Evaluation logic (the Evaluator plugins, the runner) depends only on this
    contract, never on a specific SDK — OpenAI, Gemini, or anything added later.
    Implementations never raise for expected failure modes (timeout, rate limit,
    unavailable, malformed response, authentication); they normalize those into
    `ProviderResponse.error` instead.
    """

    name: str
    model: str

    def generate(self, request: ProviderRequest) -> ProviderResponse: ...
