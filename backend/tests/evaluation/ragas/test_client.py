from unittest.mock import MagicMock

import httpx2
import openai
import pytest

from app.evaluation.ragas.client import RagasClient, RagasEvaluatorError, RagasScore
from app.providers.types import ProviderErrorType

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


class _FakeMetricResult:
    """Stands in for ragas.metrics.result.MetricResult - only .value/.reason
    are ever read by RagasClient._run."""

    def __init__(self, value, reason=None):
        self.value = value
        self.reason = reason


def _bare_client() -> RagasClient:
    """A RagasClient with __init__ skipped, for testing `_run`'s exception
    mapping in isolation without constructing a real openai.OpenAI client
    or importing ragas's metric classes."""
    return RagasClient.__new__(RagasClient)


class TestRagasClientRunSuccess:
    def test_success_returns_normalized_ragas_score(self):
        client = _bare_client()

        score = client._run(lambda: _FakeMetricResult(0.83, reason="mostly grounded"))

        assert isinstance(score, RagasScore)
        assert score.value == 0.83
        assert score.reason == "mostly grounded"

    def test_reason_defaults_to_none_when_absent(self):
        client = _bare_client()

        score = client._run(lambda: _FakeMetricResult(1.0))

        assert score.reason is None

    def test_integer_value_is_coerced_to_float(self):
        client = _bare_client()

        score = client._run(lambda: _FakeMetricResult(1))

        assert score.value == 1.0
        assert isinstance(score.value, float)


class TestRagasClientRunMalformedResult:
    def test_non_numeric_value_is_malformed_response(self):
        client = _bare_client()

        with pytest.raises(RagasEvaluatorError) as exc_info:
            client._run(lambda: _FakeMetricResult("not-a-number"))

        assert exc_info.value.error_type == ProviderErrorType.MALFORMED_RESPONSE


class TestRagasClientRunOpenAIFailures:
    def _raise(self, exc: Exception):
        def _boom():
            raise exc

        return _boom

    def test_timeout_is_normalized(self):
        client = _bare_client()
        with pytest.raises(RagasEvaluatorError) as exc_info:
            client._run(self._raise(openai.APITimeoutError(request=REQUEST)))
        assert exc_info.value.error_type == ProviderErrorType.TIMEOUT

    def test_authentication_error_is_normalized(self):
        client = _bare_client()
        exc = openai.AuthenticationError(
            "invalid api key",
            response=httpx2.Response(401, request=REQUEST, json={}),
            body=None,
        )
        with pytest.raises(RagasEvaluatorError) as exc_info:
            client._run(self._raise(exc))
        assert exc_info.value.error_type == ProviderErrorType.AUTHENTICATION

    def test_rate_limit_error_is_normalized(self):
        client = _bare_client()
        exc = openai.RateLimitError(
            "rate limited",
            response=httpx2.Response(429, request=REQUEST, json={}),
            body=None,
        )
        with pytest.raises(RagasEvaluatorError) as exc_info:
            client._run(self._raise(exc))
        assert exc_info.value.error_type == ProviderErrorType.RATE_LIMIT

    def test_connection_error_is_normalized_as_unavailable(self):
        client = _bare_client()
        with pytest.raises(RagasEvaluatorError) as exc_info:
            client._run(self._raise(openai.APIConnectionError(request=REQUEST)))
        assert exc_info.value.error_type == ProviderErrorType.UNAVAILABLE

    def test_internal_server_error_is_normalized_as_unavailable(self):
        client = _bare_client()
        exc = openai.InternalServerError(
            "server error",
            response=httpx2.Response(500, request=REQUEST, json={}),
            body=None,
        )
        with pytest.raises(RagasEvaluatorError) as exc_info:
            client._run(self._raise(exc))
        assert exc_info.value.error_type == ProviderErrorType.UNAVAILABLE


class TestRagasClientRunOtherFailures:
    def test_unexpected_exception_is_normalized_as_unavailable_not_raised_bare(self):
        """Any other failure (ragas's own exceptions, instructor retries
        exhausted, a dependency import error surfacing lazily, ...) must
        never escape as a bare exception - only RagasEvaluatorError."""
        client = _bare_client()

        def _boom():
            raise RuntimeError("ragas internal failure")

        with pytest.raises(RagasEvaluatorError) as exc_info:
            client._run(_boom)

        assert exc_info.value.error_type == ProviderErrorType.UNAVAILABLE

    def test_a_ragas_evaluator_error_raised_by_the_call_itself_passes_through(self):
        client = _bare_client()

        def _boom():
            raise RagasEvaluatorError("already normalized", error_type=ProviderErrorType.TIMEOUT)

        with pytest.raises(RagasEvaluatorError) as exc_info:
            client._run(_boom)

        assert exc_info.value.error_type == ProviderErrorType.TIMEOUT


class TestRagasClientScoreMethodsDelegate:
    """The public score_* methods just forward to the matching metric
    instance's .score(...) via _run - verified here with fakes standing in
    for the real ragas metric objects (never constructed in these tests)."""

    def _client_with_fake_metrics(self) -> RagasClient:
        client = _bare_client()
        client._faithfulness = MagicMock()
        client._answer_relevancy = MagicMock()
        client._context_precision = MagicMock()
        client._context_recall = MagicMock()
        return client

    def test_score_faithfulness_calls_metric_with_expected_kwargs(self):
        client = self._client_with_fake_metrics()
        client._faithfulness.score.return_value = _FakeMetricResult(0.9)

        score = client.score_faithfulness(user_input="q", response="r", retrieved_contexts=["ctx1"])

        client._faithfulness.score.assert_called_once_with(
            user_input="q", response="r", retrieved_contexts=["ctx1"]
        )
        assert score.value == 0.9

    def test_score_answer_relevancy_calls_metric_with_expected_kwargs(self):
        client = self._client_with_fake_metrics()
        client._answer_relevancy.score.return_value = _FakeMetricResult(0.5)

        client.score_answer_relevancy(user_input="q", response="r")

        client._answer_relevancy.score.assert_called_once_with(user_input="q", response="r")

    def test_score_context_precision_calls_metric_with_expected_kwargs(self):
        client = self._client_with_fake_metrics()
        client._context_precision.score.return_value = _FakeMetricResult(0.5)

        client.score_context_precision(user_input="q", reference="ref", retrieved_contexts=["c"])

        client._context_precision.score.assert_called_once_with(
            user_input="q", reference="ref", retrieved_contexts=["c"]
        )

    def test_score_context_recall_calls_metric_with_expected_kwargs(self):
        client = self._client_with_fake_metrics()
        client._context_recall.score.return_value = _FakeMetricResult(0.5)

        client.score_context_recall(user_input="q", reference="ref", retrieved_contexts=["c"])

        client._context_recall.score.assert_called_once_with(
            user_input="q", retrieved_contexts=["c"], reference="ref"
        )
