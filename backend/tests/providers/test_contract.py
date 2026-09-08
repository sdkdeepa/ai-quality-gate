"""Contract tests: every Provider implementation must satisfy the same shape,
regardless of what SDK (if any) backs it. Runs against DeterministicProvider
plus OpenAI/Gemini providers wired to mocked SDK clients — never a real API.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.evaluation.types import FixtureResponse
from app.providers.deterministic import DeterministicProvider
from app.providers.gemini_provider import GeminiProvider
from app.providers.openai_provider import OpenAIProvider
from app.providers.types import ProviderRequest


def _deterministic_provider() -> DeterministicProvider:
    fixture = FixtureResponse(
        response="ok", latency_ms=10.0, input_tokens=1, output_tokens=1, estimated_cost=0.0
    )
    return DeterministicProvider({"c1": fixture})


def _openai_provider() -> OpenAIProvider:
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        id="cmpl-1",
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
    )
    return OpenAIProvider("sk-test", client=client)


def _gemini_provider() -> GeminiProvider:
    client = MagicMock()
    client.models.generate_content.return_value = SimpleNamespace(
        text="ok",
        response_id="resp-1",
        usage_metadata=SimpleNamespace(prompt_token_count=1, candidates_token_count=1),
    )
    return GeminiProvider("test-key", client=client)


PROVIDER_FACTORIES = {
    "deterministic": _deterministic_provider,
    "openai": _openai_provider,
    "gemini": _gemini_provider,
}


@pytest.mark.parametrize("provider_name", sorted(PROVIDER_FACTORIES))
class TestProviderContract:
    def test_has_name_and_model(self, provider_name):
        provider = PROVIDER_FACTORIES[provider_name]()

        assert isinstance(provider.name, str) and provider.name
        assert isinstance(provider.model, str) and provider.model

    def test_generate_returns_a_provider_response_with_required_fields(self, provider_name):
        provider = PROVIDER_FACTORIES[provider_name]()

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.provider == provider.name
        assert response.model == provider.model
        assert isinstance(response.text, str)
        assert response.latency_ms >= 0
        assert response.error is None
        assert response.ok is True
