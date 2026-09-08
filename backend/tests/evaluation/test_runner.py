from datetime import UTC, datetime

import pytest

from app.core.exceptions import MissingFixtureError
from app.domain.enums import RunStatus
from app.domain.evaluation_case import EvaluationCase
from app.domain.golden_dataset import GoldenDataset
from app.evaluation.runner import EvaluationRunner
from app.evaluation.types import FixtureResponse
from app.providers.types import ProviderError, ProviderErrorType, ProviderRequest, ProviderResponse


def _dataset(cases: list[EvaluationCase]) -> GoldenDataset:
    return GoldenDataset(
        name="test_dataset",
        version="1.0.0",
        created_at=datetime.now(UTC),
        description="A test dataset.",
        cases=cases,
    )


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


def test_run_produces_completed_run_and_case_results():
    case = EvaluationCase(
        id="c1",
        name="n",
        category="c",
        query="q",
        expected_answer="ok",
        metadata={"match_mode": "exact"},
    )
    dataset = _dataset([case])
    fixtures = {"c1": _fixture(response="ok")}

    runner = EvaluationRunner()
    run, results = runner.run(dataset, fixtures)

    assert run.status == RunStatus.COMPLETED
    assert run.completed_at is not None
    assert run.dataset_version == "1.0.0"
    assert len(results) == 1
    assert results[0].case_id == "c1"
    assert results[0].passed is True


def test_run_raises_on_missing_fixture():
    case = EvaluationCase(id="c1", name="n", category="c", query="q")
    dataset = _dataset([case])

    runner = EvaluationRunner()

    with pytest.raises(MissingFixtureError):
        runner.run(dataset, {})


def test_case_with_no_applicable_evaluators_passes_vacuously():
    case = EvaluationCase(id="c1", name="n", category="c", query="q")
    dataset = _dataset([case])
    fixtures = {"c1": _fixture(latency_ms=100.0, estimated_cost=0.001)}

    runner = EvaluationRunner()
    _, results = runner.run(dataset, fixtures)

    assert results[0].passed is True


def test_non_critical_case_failure_does_not_set_critical_failure():
    case = EvaluationCase(
        id="c1",
        name="n",
        category="c",
        query="q",
        critical=False,
        metadata={"required_phrases": ["missing phrase"]},
    )
    dataset = _dataset([case])
    fixtures = {"c1": _fixture(response="does not contain it")}

    runner = EvaluationRunner()
    _, results = runner.run(dataset, fixtures)

    assert results[0].passed is False
    assert results[0].critical_failure is False


def test_critical_case_failure_sets_critical_failure_flag():
    case = EvaluationCase(
        id="c1",
        name="n",
        category="c",
        query="q",
        critical=True,
        metadata={"required_phrases": ["missing phrase"]},
    )
    dataset = _dataset([case])
    fixtures = {"c1": _fixture(response="does not contain it")}

    runner = EvaluationRunner()
    _, results = runner.run(dataset, fixtures)

    assert results[0].passed is False
    assert results[0].critical_failure is True


def test_critical_case_pass_does_not_set_critical_failure():
    case = EvaluationCase(
        id="c1",
        name="n",
        category="c",
        query="q",
        critical=True,
        metadata={"required_phrases": ["match"]},
    )
    dataset = _dataset([case])
    fixtures = {"c1": _fixture(response="a match here")}

    runner = EvaluationRunner()
    _, results = runner.run(dataset, fixtures)

    assert results[0].passed is True
    assert results[0].critical_failure is False


class FakeProvider:
    """A minimal Provider stub used to test run_with_provider without any real SDK."""

    def __init__(self, name: str = "fake", model: str = "fake-model") -> None:
        self.name = name
        self.model = model
        self._responses: dict[str, ProviderResponse] = {}
        self.requests: list[ProviderRequest] = []

    def set_response(self, case_id: str, response: ProviderResponse) -> None:
        self._responses[case_id] = response

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return self._responses[request.case_id]


def _provider_response(**overrides) -> ProviderResponse:
    defaults = {"provider": "fake", "model": "fake-model", "text": "ok", "latency_ms": 10.0}
    defaults.update(overrides)
    return ProviderResponse(**defaults)


class TestRunWithProvider:
    def test_run_with_provider_produces_completed_run(self):
        case = EvaluationCase(
            id="c1", name="n", category="c", query="q", metadata={"required_phrases": ["ok"]}
        )
        dataset = _dataset([case])
        provider = FakeProvider(name="fake", model="fake-model")
        provider.set_response("c1", _provider_response(text="ok"))

        runner = EvaluationRunner()
        run, results = runner.run_with_provider(dataset, provider)

        assert run.status == RunStatus.COMPLETED
        assert run.provider == "fake"
        assert run.model == "fake-model"
        assert results[0].passed is True
        assert results[0].response == "ok"

    def test_case_query_becomes_the_provider_request_prompt(self):
        case = EvaluationCase(id="c1", name="n", category="c", query="what is the return policy?")
        dataset = _dataset([case])
        provider = FakeProvider()
        provider.set_response("c1", _provider_response())

        EvaluationRunner().run_with_provider(dataset, provider)

        assert provider.requests[0].case_id == "c1"
        assert provider.requests[0].prompt == "what is the return policy?"

    def test_case_json_schema_metadata_is_forwarded_to_the_provider_request(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        case = EvaluationCase(
            id="c1", name="n", category="c", query="q", metadata={"json_schema": schema}
        )
        dataset = _dataset([case])
        provider = FakeProvider()
        provider.set_response("c1", _provider_response(text='{"a": "x"}'))

        EvaluationRunner().run_with_provider(dataset, provider)

        assert provider.requests[0].json_schema == schema

    def test_provider_error_produces_failed_case_result_without_running_evaluators(self):
        case = EvaluationCase(
            id="c1", name="n", category="c", query="q", metadata={"required_phrases": ["ok"]}
        )
        dataset = _dataset([case])
        provider = FakeProvider()
        provider.set_response(
            "c1",
            _provider_response(
                error=ProviderError(error_type=ProviderErrorType.TIMEOUT, message="took too long")
            ),
        )

        _, results = EvaluationRunner().run_with_provider(dataset, provider)

        assert results[0].passed is False
        assert results[0].metric_results == []
        assert results[0].error == {"error_type": "timeout", "message": "took too long"}

    def test_provider_error_on_critical_case_sets_critical_failure(self):
        case = EvaluationCase(id="c1", name="n", category="c", query="q", critical=True)
        dataset = _dataset([case])
        provider = FakeProvider()
        provider.set_response(
            "c1",
            _provider_response(
                error=ProviderError(
                    error_type=ProviderErrorType.AUTHENTICATION, message="bad api key"
                )
            ),
        )

        _, results = EvaluationRunner().run_with_provider(dataset, provider)

        assert results[0].critical_failure is True

    def test_retrieved_context_from_provider_response_is_used_for_citation_evaluator(self):
        case = EvaluationCase(
            id="c1", name="n", category="c", query="q", metadata={"requires_citation": True}
        )
        dataset = _dataset([case])
        provider = FakeProvider()
        provider.set_response("c1", _provider_response(retrieved_context=["some source"]))

        _, results = EvaluationRunner().run_with_provider(dataset, provider)

        assert results[0].passed is True
        assert results[0].retrieved_context == ["some source"]

    def test_missing_token_and_cost_fields_default_to_zero_on_case_result(self):
        case = EvaluationCase(id="c1", name="n", category="c", query="q")
        dataset = _dataset([case])
        provider = FakeProvider()
        provider.set_response(
            "c1", _provider_response(input_tokens=None, output_tokens=None, estimated_cost=None)
        )

        _, results = EvaluationRunner().run_with_provider(dataset, provider)

        assert results[0].input_tokens == 0
        assert results[0].output_tokens == 0
        assert results[0].estimated_cost == 0.0
