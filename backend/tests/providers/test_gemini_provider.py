from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from google.genai import errors

from app.providers.gemini_provider import GeminiProvider
from app.providers.types import ProviderErrorType, ProviderRequest


def _fake_response(
    text: str = "hello",
    *,
    prompt_tokens: int = 5,
    candidates_tokens: int = 3,
    response_id: str = "resp-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        response_id=response_id,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens, candidates_token_count=candidates_tokens
        ),
    )


def _provider(client: MagicMock) -> GeminiProvider:
    return GeminiProvider("test-key", model="gemini-2.5-flash", client=client)


class TestGeminiProviderSuccess:
    def test_generate_returns_normalized_response(self):
        client = MagicMock()
        client.models.generate_content.return_value = _fake_response("hi there")
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.provider == "gemini"
        assert response.model == "gemini-2.5-flash"
        assert response.text == "hi there"
        assert response.input_tokens == 5
        assert response.output_tokens == 3
        assert response.estimated_cost is not None
        assert response.request_id == "resp-1"
        assert response.error is None

    def test_json_schema_request_passes_schema_through_and_parses_output(self):
        client = MagicMock()
        client.models.generate_content.return_value = _fake_response('{"a": 1}')
        provider = _provider(client)

        response = provider.generate(
            ProviderRequest(case_id="c1", prompt="hello", json_schema={"type": "array"})
        )

        kwargs = client.models.generate_content.call_args.kwargs
        assert kwargs["config"].response_mime_type == "application/json"
        assert kwargs["config"].response_json_schema == {"type": "array"}
        assert response.structured_output == {"a": 1}

    def test_non_json_output_for_schema_request_leaves_structured_output_none(self):
        client = MagicMock()
        client.models.generate_content.return_value = _fake_response("not json")
        provider = _provider(client)

        response = provider.generate(
            ProviderRequest(case_id="c1", prompt="hello", json_schema={"type": "object"})
        )

        assert response.structured_output is None
        assert response.error is None

    def test_unknown_model_still_returns_cost_of_zero(self):
        client = MagicMock()
        client.models.generate_content.return_value = _fake_response()
        provider = GeminiProvider("test-key", model="totally-unknown-model", client=client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.estimated_cost == 0.0


class TestGeminiProviderNormalizedFailures:
    def test_timeout_is_normalized(self):
        client = MagicMock()
        client.models.generate_content.side_effect = httpx.TimeoutException("timed out")
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.TIMEOUT

    def test_authentication_error_is_normalized(self):
        client = MagicMock()
        client.models.generate_content.side_effect = errors.ClientError(
            401, {"error": {"message": "API key not valid", "status": "UNAUTHENTICATED"}}
        )
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.AUTHENTICATION

    def test_permission_denied_message_is_classified_as_authentication(self):
        client = MagicMock()
        client.models.generate_content.side_effect = errors.ClientError(
            400,
            {"error": {"message": "Permission denied on API key", "status": "PERMISSION_DENIED"}},
        )
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.AUTHENTICATION

    def test_rate_limit_error_is_normalized(self):
        client = MagicMock()
        client.models.generate_content.side_effect = errors.ClientError(
            429, {"error": {"message": "rate limit exceeded"}}
        )
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.RATE_LIMIT

    def test_other_client_error_is_normalized_as_unavailable(self):
        client = MagicMock()
        client.models.generate_content.side_effect = errors.ClientError(
            400, {"error": {"message": "bad request"}}
        )
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.UNAVAILABLE

    def test_server_error_is_normalized_as_unavailable(self):
        client = MagicMock()
        client.models.generate_content.side_effect = errors.ServerError(
            503, {"error": {"message": "unavailable"}}
        )
        provider = _provider(client)

        response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))

        assert response.error.error_type == ProviderErrorType.UNAVAILABLE

    def test_a_failed_case_never_raises(self):
        client = MagicMock()
        client.models.generate_content.side_effect = httpx.TimeoutException("timed out")
        provider = _provider(client)

        try:
            response = provider.generate(ProviderRequest(case_id="c1", prompt="hello"))
        except Exception as exc:  # noqa: BLE001 - explicitly asserting generate() never raises
            pytest.fail(f"generate() raised {exc!r} instead of returning a normalized error")

        assert response.error is not None
