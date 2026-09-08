from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx2
import openai
import pytest

from app.providers.openai_provider import OpenAIProvider
from app.providers.types import ProviderErrorType, ProviderRequest

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


def _fake_completion(
    text: str = "hello",
    *,
    prompt_tokens: int = 5,
    completion_tokens: int = 3,
    request_id: str = "cmpl-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=request_id,
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens),
    )


def _provider(client: MagicMock) -> OpenAIProvider:
    return OpenAIProvider("sk-test", model="gpt-4o-mini", client=client)


class TestOpenAIProviderSuccess:
    def test_generate_returns_normalized_response(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_completion("hi there")
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.provider == "openai"
        assert response.model == "gpt-4o-mini"
        assert response.text == "hi there"
        assert response.input_tokens == 5
        assert response.output_tokens == 3
        assert response.estimated_cost is not None
        assert response.request_id == "cmpl-1"
        assert response.latency_ms >= 0
        assert response.error is None

    def test_json_schema_request_sets_response_format_and_parses_output(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_completion('{"a": 1}')
        provider = _provider(client)

        response = provider.generate(
            ProviderRequest(case_id="c1", prompt="hello", json_schema={"type": "object"})
        )

        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}
        assert response.structured_output == {"a": 1}

    def test_non_json_output_for_schema_request_leaves_structured_output_none(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_completion("not json")
        provider = _provider(client)

        response = provider.generate(
            ProviderRequest(case_id="c1", prompt="hello", json_schema={"type": "object"})
        )

        assert response.structured_output is None
        assert response.error is None
        assert response.text == "not json"

    def test_unknown_model_still_returns_cost_of_zero(self):
        client = MagicMock()
        client.chat.completions.create.return_value = _fake_completion()
        provider = OpenAIProvider("sk-test", model="totally-unknown-model", client=client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.estimated_cost == 0.0


class TestOpenAIProviderNormalizedFailures:
    def test_timeout_is_normalized(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = openai.APITimeoutError(request=REQUEST)
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error is not None
        assert response.error.error_type == ProviderErrorType.TIMEOUT
        assert response.ok is False

    def test_authentication_error_is_normalized(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = openai.AuthenticationError(
            "invalid api key",
            response=httpx2.Response(401, request=REQUEST, json={}),
            body=None,
        )
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.AUTHENTICATION

    def test_rate_limit_error_is_normalized(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = openai.RateLimitError(
            "rate limited",
            response=httpx2.Response(429, request=REQUEST, json={}),
            body=None,
        )
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.RATE_LIMIT

    def test_connection_error_is_normalized_as_unavailable(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = openai.APIConnectionError(request=REQUEST)
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.UNAVAILABLE

    def test_internal_server_error_is_normalized_as_unavailable(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = openai.InternalServerError(
            "server error",
            response=httpx2.Response(500, request=REQUEST, json={}),
            body=None,
        )
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.UNAVAILABLE

    def test_malformed_response_when_choices_empty(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            id="cmpl-1", choices=[], usage=None
        )
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.MALFORMED_RESPONSE

    def test_a_failed_case_never_raises(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = openai.APITimeoutError(request=REQUEST)
        provider = _provider(client)

        try:
            response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))
        except Exception as exc:  # noqa: BLE001 - explicitly asserting generate() never raises
            pytest.fail(f"generate() raised {exc!r} instead of returning a normalized error")

        assert response.error is not None
