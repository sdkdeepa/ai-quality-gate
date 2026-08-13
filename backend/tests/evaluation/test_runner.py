from datetime import UTC, datetime

import pytest

from app.core.exceptions import MissingFixtureError
from app.domain.enums import RunStatus
from app.domain.evaluation_case import EvaluationCase
from app.domain.golden_dataset import GoldenDataset
from app.evaluation.runner import EvaluationRunner
from app.evaluation.types import FixtureResponse


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
