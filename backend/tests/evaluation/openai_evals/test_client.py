from unittest.mock import MagicMock

import httpx2
import openai
import pytest
from pydantic import BaseModel

from app.evaluation.openai_evals.client import (
    LabelGraderResult,
    OpenAIEvalsAdapter,
    OpenAIEvalsEvaluatorError,
    StructuredCorrectnessResult,
)
from app.providers.types import ProviderErrorType

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")


def _adapter() -> OpenAIEvalsAdapter:
    """A real OpenAIEvalsAdapter (construction makes no network call), with
    `_client.responses.parse` replaced by a MagicMock for each test."""
    adapter = OpenAIEvalsAdapter(api_key="sk-fake", judge_model="gpt-4o-mini", timeout_seconds=5.0)
    adapter._client = MagicMock()
    return adapter


class _FakeParsedResponse:
    def __init__(self, output_parsed):
        self.output_parsed = output_parsed


class TestRunExceptionMapping:
    """_run()'s mapping is exercised directly, same as the ragas/deepeval
    client tests, since it's the shared plumbing behind both public methods."""

    def _raise(self, exc: Exception):
        def _boom():
            raise exc

        return _boom

    def test_timeout_is_normalized(self):
        adapter = _adapter()
        with pytest.raises(OpenAIEvalsEvaluatorError) as exc_info:
            adapter._run(self._raise(openai.APITimeoutError(request=REQUEST)))
        assert exc_info.value.error_type == ProviderErrorType.TIMEOUT

    def test_authentication_error_is_normalized(self):
        adapter = _adapter()
        exc = openai.AuthenticationError(
            "invalid api key", response=httpx2.Response(401, request=REQUEST, json={}), body=None
        )
        with pytest.raises(OpenAIEvalsEvaluatorError) as exc_info:
            adapter._run(self._raise(exc))
        assert exc_info.value.error_type == ProviderErrorType.AUTHENTICATION

    def test_rate_limit_error_is_normalized(self):
        adapter = _adapter()
        exc = openai.RateLimitError(
            "rate limited", response=httpx2.Response(429, request=REQUEST, json={}), body=None
        )
        with pytest.raises(OpenAIEvalsEvaluatorError) as exc_info:
            adapter._run(self._raise(exc))
        assert exc_info.value.error_type == ProviderErrorType.RATE_LIMIT

    def test_connection_error_is_normalized_as_unavailable(self):
        adapter = _adapter()
        with pytest.raises(OpenAIEvalsEvaluatorError) as exc_info:
            adapter._run(self._raise(openai.APIConnectionError(request=REQUEST)))
        assert exc_info.value.error_type == ProviderErrorType.UNAVAILABLE

    def test_unexpected_exception_is_normalized_not_raised_bare(self):
        adapter = _adapter()

        def _boom():
            raise RuntimeError("dependency failure")

        with pytest.raises(OpenAIEvalsEvaluatorError) as exc_info:
            adapter._run(_boom)
        assert exc_info.value.error_type == ProviderErrorType.UNAVAILABLE

    def test_an_openai_evals_evaluator_error_raised_by_the_call_itself_passes_through(self):
        adapter = _adapter()

        def _boom():
            raise OpenAIEvalsEvaluatorError(
                "already normalized", error_type=ProviderErrorType.TIMEOUT
            )

        with pytest.raises(OpenAIEvalsEvaluatorError) as exc_info:
            adapter._run(_boom)
        assert exc_info.value.error_type == ProviderErrorType.TIMEOUT

    def test_pydantic_validation_error_is_malformed_response(self):
        from pydantic import ValidationError

        adapter = _adapter()

        class _M(BaseModel):
            x: int

        def _boom():
            try:
                _M(x="not-an-int")
            except ValidationError as exc:
                raise exc

        with pytest.raises(OpenAIEvalsEvaluatorError) as exc_info:
            adapter._run(_boom)
        assert exc_info.value.error_type == ProviderErrorType.MALFORMED_RESPONSE


class TestLabelSchemaCache:
    def test_same_label_set_reuses_cached_schema(self):
        adapter = _adapter()
        schema1 = adapter._label_schema(("a", "b"))
        schema2 = adapter._label_schema(("a", "b"))
        assert schema1 is schema2

    def test_different_label_set_builds_a_new_schema(self):
        adapter = _adapter()
        schema1 = adapter._label_schema(("a", "b"))
        schema2 = adapter._label_schema(("a", "b", "c"))
        assert schema1 is not schema2

    def test_schema_rejects_a_label_outside_the_allowed_set(self):
        from pydantic import ValidationError

        adapter = _adapter()
        schema = adapter._label_schema(("a", "b"))
        with pytest.raises(ValidationError):
            schema(label="c", reasoning="x")

    def test_schema_accepts_an_allowed_label(self):
        adapter = _adapter()
        schema = adapter._label_schema(("a", "b"))
        instance = schema(label="a", reasoning="fits")
        assert instance.label == "a"


class TestClassifyLabel:
    def test_returns_passed_true_when_label_in_passing_set(self):
        adapter = _adapter()
        schema = adapter._label_schema(("compliant", "non_compliant"))
        parsed = schema(label="compliant", reasoning="matches policy")
        adapter._client.responses.parse.return_value = _FakeParsedResponse(parsed)

        result = adapter.classify_label(
            instructions="Classify compliance.",
            labels=["compliant", "non_compliant"],
            passing_labels=["compliant"],
            input_text="q",
            actual_output="a",
        )

        assert isinstance(result, LabelGraderResult)
        assert result.label == "compliant"
        assert result.passed is True
        assert result.reasoning == "matches policy"

    def test_returns_passed_false_when_label_not_in_passing_set(self):
        adapter = _adapter()
        schema = adapter._label_schema(("compliant", "non_compliant"))
        parsed = schema(label="non_compliant", reasoning="violates policy")
        adapter._client.responses.parse.return_value = _FakeParsedResponse(parsed)

        result = adapter.classify_label(
            instructions="Classify compliance.",
            labels=["compliant", "non_compliant"],
            passing_labels=["compliant"],
            input_text="q",
            actual_output="a",
        )

        assert result.passed is False

    def test_none_output_parsed_is_malformed_response(self):
        adapter = _adapter()
        adapter._client.responses.parse.return_value = _FakeParsedResponse(None)

        with pytest.raises(OpenAIEvalsEvaluatorError) as exc_info:
            adapter.classify_label(
                instructions="x",
                labels=["a", "b"],
                passing_labels=["a"],
                input_text="q",
                actual_output="a",
            )
        assert exc_info.value.error_type == ProviderErrorType.MALFORMED_RESPONSE


class TestScoreStructuredFacts:
    def test_computes_fraction_of_supported_facts(self):
        from app.evaluation.openai_evals.client import _FactCheckJudgment, _FactJudgment

        adapter = _adapter()
        parsed = _FactCheckJudgment(
            fact_checks=[
                _FactJudgment(fact="30-day return window", supported=True),
                _FactJudgment(fact="free return shipping", supported=False),
            ],
            reasoning="one of two facts confirmed",
        )
        adapter._client.responses.parse.return_value = _FakeParsedResponse(parsed)

        result = adapter.score_structured_facts(
            expected_facts=["30-day return window", "free return shipping"],
            input_text="q",
            actual_output="a",
        )

        assert isinstance(result, StructuredCorrectnessResult)
        assert result.score == 0.5
        assert result.supported_facts == ["30-day return window"]
        assert result.unsupported_facts == ["free return shipping"]

    def test_empty_expected_facts_yields_zero_score_not_division_error(self):
        from app.evaluation.openai_evals.client import _FactCheckJudgment

        adapter = _adapter()
        parsed = _FactCheckJudgment(fact_checks=[], reasoning="nothing to check")
        adapter._client.responses.parse.return_value = _FakeParsedResponse(parsed)

        result = adapter.score_structured_facts(
            expected_facts=[], input_text="q", actual_output="a"
        )

        assert result.score == 0.0

    def test_none_output_parsed_is_malformed_response(self):
        adapter = _adapter()
        adapter._client.responses.parse.return_value = _FakeParsedResponse(None)

        with pytest.raises(OpenAIEvalsEvaluatorError) as exc_info:
            adapter.score_structured_facts(expected_facts=["x"], input_text="q", actual_output="a")
        assert exc_info.value.error_type == ProviderErrorType.MALFORMED_RESPONSE
