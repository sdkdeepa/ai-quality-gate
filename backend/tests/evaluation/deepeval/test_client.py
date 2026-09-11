from unittest.mock import MagicMock

import httpx2
import openai
import pytest
from deepeval.errors import DeepEvalError

from app.evaluation.deepeval.client import DeepEvalClient, DeepEvalEvaluatorError, DeepEvalScore
from app.providers.types import ProviderErrorType

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


class _FakeMetric:
    """Stands in for a `deepeval.metrics.GEval` instance after `.measure()`
    has populated `.score`/`.reason` - only those two attributes are ever
    read by `DeepEvalClient._run`."""

    def __init__(self, score, reason=None):
        self.score = score
        self.reason = reason


def _bare_client() -> DeepEvalClient:
    """A DeepEvalClient with __init__ skipped - tests `_run`'s exception
    mapping without constructing a real OpenAIModel or importing deepeval's
    metric classes."""
    return DeepEvalClient.__new__(DeepEvalClient)


class TestDeepEvalClientRunSuccess:
    def test_success_returns_normalized_score(self):
        client = _bare_client()

        score = client._run(lambda: _FakeMetric(0.83, reason="mostly on-criteria"))

        assert isinstance(score, DeepEvalScore)
        assert score.value == 0.83
        assert score.reason == "mostly on-criteria"

    def test_reason_defaults_to_none_when_absent(self):
        client = _bare_client()

        score = client._run(lambda: _FakeMetric(1.0))

        assert score.reason is None

    def test_integer_score_is_coerced_to_float(self):
        client = _bare_client()

        score = client._run(lambda: _FakeMetric(1))

        assert score.value == 1.0
        assert isinstance(score.value, float)


class TestDeepEvalClientRunMalformedResult:
    def test_non_numeric_score_is_malformed_response(self):
        client = _bare_client()

        with pytest.raises(DeepEvalEvaluatorError) as exc_info:
            client._run(lambda: _FakeMetric("not-a-number"))

        assert exc_info.value.error_type == ProviderErrorType.MALFORMED_RESPONSE


class TestDeepEvalClientRunOpenAIFailures:
    def _raise(self, exc: Exception):
        def _boom():
            raise exc

        return _boom

    def test_timeout_is_normalized(self):
        client = _bare_client()
        with pytest.raises(DeepEvalEvaluatorError) as exc_info:
            client._run(self._raise(openai.APITimeoutError(request=REQUEST)))
        assert exc_info.value.error_type == ProviderErrorType.TIMEOUT

    def test_authentication_error_is_normalized(self):
        client = _bare_client()
        exc = openai.AuthenticationError(
            "invalid api key",
            response=httpx2.Response(401, request=REQUEST, json={}),
            body=None,
        )
        with pytest.raises(DeepEvalEvaluatorError) as exc_info:
            client._run(self._raise(exc))
        assert exc_info.value.error_type == ProviderErrorType.AUTHENTICATION

    def test_rate_limit_error_is_normalized(self):
        client = _bare_client()
        exc = openai.RateLimitError(
            "rate limited",
            response=httpx2.Response(429, request=REQUEST, json={}),
            body=None,
        )
        with pytest.raises(DeepEvalEvaluatorError) as exc_info:
            client._run(self._raise(exc))
        assert exc_info.value.error_type == ProviderErrorType.RATE_LIMIT

    def test_connection_error_is_normalized_as_unavailable(self):
        client = _bare_client()
        with pytest.raises(DeepEvalEvaluatorError) as exc_info:
            client._run(self._raise(openai.APIConnectionError(request=REQUEST)))
        assert exc_info.value.error_type == ProviderErrorType.UNAVAILABLE

    def test_internal_server_error_is_normalized_as_unavailable(self):
        client = _bare_client()
        exc = openai.InternalServerError(
            "server error",
            response=httpx2.Response(500, request=REQUEST, json={}),
            body=None,
        )
        with pytest.raises(DeepEvalEvaluatorError) as exc_info:
            client._run(self._raise(exc))
        assert exc_info.value.error_type == ProviderErrorType.UNAVAILABLE


class TestDeepEvalClientRunDeepEvalFailures:
    def test_deepeval_error_is_normalized_as_unavailable(self):
        client = _bare_client()

        def _boom():
            raise DeepEvalError("malformed judge response")

        with pytest.raises(DeepEvalEvaluatorError) as exc_info:
            client._run(_boom)

        assert exc_info.value.error_type == ProviderErrorType.UNAVAILABLE


class TestDeepEvalClientRunOtherFailures:
    def test_unexpected_exception_is_normalized_not_raised_bare(self):
        client = _bare_client()

        def _boom():
            raise RuntimeError("dependency failure")

        with pytest.raises(DeepEvalEvaluatorError) as exc_info:
            client._run(_boom)

        assert exc_info.value.error_type == ProviderErrorType.UNAVAILABLE

    def test_a_deepeval_evaluator_error_raised_by_the_call_itself_passes_through(self):
        client = _bare_client()

        def _boom():
            raise DeepEvalEvaluatorError("already normalized", error_type=ProviderErrorType.TIMEOUT)

        with pytest.raises(DeepEvalEvaluatorError) as exc_info:
            client._run(_boom)

        assert exc_info.value.error_type == ProviderErrorType.TIMEOUT


class TestDeepEvalClientScoreCriteriaInputTranslation:
    """score_criteria() builds the LLMTestCase/evaluation_params based on
    which optional fields are provided, and caches metrics by their
    (name, criteria, params, threshold) signature."""

    def _client(self) -> DeepEvalClient:
        client = _bare_client()
        client._metric_cache = {}
        return client

    def test_builds_metric_with_only_required_params_when_optional_fields_absent(self):
        client = self._client()
        built_params = {}

        def _fake_build_metric(*, name, criteria, params, threshold):
            built_params["params"] = params
            metric = MagicMock()
            metric.measure.return_value = None
            metric.score = 0.9
            metric.reason = None
            return metric

        client._build_metric = _fake_build_metric

        client.score_criteria(
            name="criteria",
            criteria="Is it polite?",
            threshold=0.7,
            input_text="hi",
            actual_output="hello!",
        )

        from deepeval.test_case import SingleTurnParams

        assert built_params["params"] == [
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
        ]

    def test_builds_metric_with_all_params_when_all_optional_fields_present(self):
        client = self._client()
        built_params = {}

        def _fake_build_metric(*, name, criteria, params, threshold):
            built_params["params"] = params
            metric = MagicMock()
            metric.score = 0.9
            metric.reason = None
            return metric

        client._build_metric = _fake_build_metric

        client.score_criteria(
            name="criteria",
            criteria="Is it grounded?",
            threshold=0.7,
            input_text="q",
            actual_output="a",
            expected_output="expected",
            context=["ctx1"],
            retrieval_context=["retrieved1"],
        )

        from deepeval.test_case import SingleTurnParams

        assert built_params["params"] == [
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
            SingleTurnParams.EXPECTED_OUTPUT,
            SingleTurnParams.CONTEXT,
            SingleTurnParams.RETRIEVAL_CONTEXT,
        ]

    def test_reuses_cached_metric_for_identical_signature(self):
        client = self._client()
        build_calls = []

        def _fake_build_metric(*, name, criteria, params, threshold):
            build_calls.append(1)
            metric = MagicMock()
            metric.score = 0.9
            metric.reason = None
            return metric

        client._build_metric = _fake_build_metric

        client.score_criteria(
            name="criteria",
            criteria="Is it polite?",
            threshold=0.7,
            input_text="q1",
            actual_output="a1",
        )
        client.score_criteria(
            name="criteria",
            criteria="Is it polite?",
            threshold=0.7,
            input_text="q2",
            actual_output="a2",
        )

        assert len(build_calls) == 1

    def test_builds_a_new_metric_for_a_different_criteria_string(self):
        client = self._client()
        build_calls = []

        def _fake_build_metric(*, name, criteria, params, threshold):
            build_calls.append(criteria)
            metric = MagicMock()
            metric.score = 0.9
            metric.reason = None
            return metric

        client._build_metric = _fake_build_metric

        client.score_criteria(
            name="criteria",
            criteria="Is it polite?",
            threshold=0.7,
            input_text="q",
            actual_output="a",
        )
        client.score_criteria(
            name="criteria",
            criteria="Is it professional?",
            threshold=0.7,
            input_text="q",
            actual_output="a",
        )

        assert build_calls == ["Is it polite?", "Is it professional?"]
