from app.evaluation.types import FixtureResponse
from app.providers.deterministic import DeterministicProvider
from app.providers.types import ProviderErrorType, ProviderRequest


def _fixture(**overrides) -> FixtureResponse:
    defaults = {
        "response": "ok",
        "retrieved_context": [],
        "latency_ms": 500.0,
        "input_tokens": 10,
        "output_tokens": 10,
        "estimated_cost": 0.01,
    }
    defaults.update(overrides)
    return FixtureResponse(**defaults)


class TestDeterministicProvider:
    def test_returns_fixture_fields_verbatim(self):
        provider = DeterministicProvider(
            {"c1": _fixture(response="hello", retrieved_context=["ctx"])}
        )

        response = provider.generate(ProviderRequest(case_id="c1", prompt="q"))

        assert response.provider == "deterministic"
        assert response.model == "fixture-v1"
        assert response.text == "hello"
        assert response.retrieved_context == ["ctx"]
        assert response.latency_ms == 500.0
        assert response.input_tokens == 10
        assert response.output_tokens == 10
        assert response.estimated_cost == 0.01
        assert response.error is None
        assert response.ok is True

    def test_custom_model_and_name_are_reported(self):
        provider = DeterministicProvider(
            {"c1": _fixture()}, model="fixture-v2", name="deterministic-alt"
        )

        response = provider.generate(ProviderRequest(case_id="c1", prompt="q"))

        assert response.provider == "deterministic-alt"
        assert response.model == "fixture-v2"

    def test_missing_fixture_returns_normalized_error(self):
        provider = DeterministicProvider({})

        response = provider.generate(ProviderRequest(case_id="missing", prompt="q"))

        assert response.error is not None
        assert response.error.error_type == ProviderErrorType.MALFORMED_RESPONSE
        assert response.ok is False

    def test_json_schema_request_parses_structured_output(self):
        provider = DeterministicProvider({"c1": _fixture(response='{"a": 1}')})

        response = provider.generate(
            ProviderRequest(case_id="c1", prompt="q", json_schema={"type": "object"})
        )

        assert response.structured_output == {"a": 1}

    def test_json_schema_request_with_non_json_response_leaves_structured_output_none(self):
        provider = DeterministicProvider({"c1": _fixture(response="not json")})

        response = provider.generate(
            ProviderRequest(case_id="c1", prompt="q", json_schema={"type": "object"})
        )

        assert response.structured_output is None
        assert response.text == "not json"

    def test_no_json_schema_leaves_structured_output_none(self):
        provider = DeterministicProvider({"c1": _fixture(response='{"a": 1}')})

        response = provider.generate(ProviderRequest(case_id="c1", prompt="q"))

        assert response.structured_output is None
