"""Sprint 6 requirement #4/#7: a case run through EvaluationRunner produces
deterministic + RAGAS + DeepEval MetricResults together, framework selection
via `frameworks=` correctly filters, and existing deterministic/RAGAS
behavior is unchanged by adding DeepEval.

Uses fake Evaluators standing in for the real RAGAS/DeepEval ones (no
ragas/deepeval imports here) - the behavior under test is entirely
`EvaluationRunner`'s and the `Evaluator` protocol's.
"""

from datetime import UTC, datetime

from app.domain.evaluation_case import EvaluationCase
from app.domain.golden_dataset import GoldenDataset
from app.domain.metric_result import MetricResult
from app.evaluation.deterministic import DEFAULT_EVALUATORS
from app.evaluation.runner import EvaluationRunner
from app.evaluation.types import FixtureResponse


class _FakeEvaluator:
    def __init__(self, name: str, framework: str, score: float = 0.9, threshold: float = 0.7):
        self.name = name
        self.framework = framework
        self._score = score
        self._threshold = threshold

    def applies_to(self, case: EvaluationCase) -> bool:
        return True

    def evaluate(self, evaluation_input) -> MetricResult:
        return MetricResult(
            metric_name=self.name,
            score=self._score,
            threshold=self._threshold,
            passed=self._score >= self._threshold,
            framework=self.framework,
            metadata={"status": "scored"},
        )


def _dataset(cases: list[EvaluationCase]) -> GoldenDataset:
    return GoldenDataset(
        name="test_dataset",
        version="1.0.0",
        created_at=datetime.now(UTC),
        description="A test dataset.",
        cases=cases,
    )


def _fixtures_for(case_id: str) -> dict[str, FixtureResponse]:
    return {
        case_id: FixtureResponse(
            response="a response",
            latency_ms=100.0,
            input_tokens=5,
            output_tokens=5,
            estimated_cost=0.001,
        )
    }


def _all_three_evaluators() -> list:
    return [
        *DEFAULT_EVALUATORS,
        _FakeEvaluator("ragas_fake", "ragas"),
        _FakeEvaluator("deepeval_fake", "deepeval"),
    ]


def _one_case() -> EvaluationCase:
    return EvaluationCase(
        id="case-1",
        name="n",
        category="answer",
        query="what is 2+2?",
        expected_answer="4",
        metadata={"match_mode": "exact"},
    )


def test_all_three_frameworks_contribute_metric_results_by_default():
    case = _one_case()
    runner = EvaluationRunner(evaluators=_all_three_evaluators())

    _, results = runner.run(_dataset([case]), _fixtures_for("case-1"))
    [result] = results

    assert {m.framework for m in result.metric_results} == {"deterministic", "ragas", "deepeval"}


def test_frameworks_filter_restricts_to_selected_subset():
    case = _one_case()
    runner = EvaluationRunner(evaluators=_all_three_evaluators())

    _, results = runner.run(
        _dataset([case]), _fixtures_for("case-1"), frameworks={"deterministic", "ragas"}
    )
    [result] = results

    assert {m.framework for m in result.metric_results} == {"deterministic", "ragas"}


def test_frameworks_filter_can_select_a_single_framework():
    case = _one_case()
    runner = EvaluationRunner(evaluators=_all_three_evaluators())

    _, results = runner.run(_dataset([case]), _fixtures_for("case-1"), frameworks={"deepeval"})
    [result] = results

    assert {m.framework for m in result.metric_results} == {"deepeval"}


def test_frameworks_filter_with_unknown_framework_yields_no_results_from_it():
    case = _one_case()
    runner = EvaluationRunner(evaluators=_all_three_evaluators())

    _, results = runner.run(
        _dataset([case]), _fixtures_for("case-1"), frameworks={"not_a_real_framework"}
    )
    [result] = results

    assert result.metric_results == []
    # No matching evaluators -> nothing to grade -> vacuously passed, same
    # rule as an empty metric_results list from Sprint 1-5.
    assert result.passed is True


def test_evaluate_case_also_respects_frameworks_filter():
    """RAGService and similar single-case callers go through evaluate_case
    directly, not run() - must filter identically."""
    from app.providers.deterministic import DeterministicProvider

    case = _one_case()
    provider = DeterministicProvider(_fixtures_for("case-1"))
    runner = EvaluationRunner(evaluators=_all_three_evaluators())

    result = runner.evaluate_case(case, provider, frameworks={"ragas"})

    assert {m.framework for m in result.metric_results} == {"ragas"}


def test_omitting_frameworks_preserves_sprint_1_through_5_default_behavior():
    """No `frameworks` argument at all (not just None) behaves exactly like
    before Sprint 6 introduced the parameter."""
    case = _one_case()
    runner = EvaluationRunner()  # DEFAULT_EVALUATORS only
    fixtures = {
        "case-1": FixtureResponse(
            response="4", latency_ms=100.0, input_tokens=5, output_tokens=5, estimated_cost=0.001
        )
    }

    _, results = runner.run(_dataset([case]), fixtures)
    [result] = results

    assert {m.framework for m in result.metric_results} == {"deterministic"}
    assert result.passed is True
