"""Sprint 7: a case run through EvaluationRunner can produce
deterministic + RAGAS + DeepEval + OpenAI-Evals-concept MetricResults
together, and the `frameworks` filter (Sprint 6) correctly includes/excludes
"openai_evals" alongside the other three. Uses a fake Evaluator standing in
for the real openai_evals one (no `openai` network calls here) - mirrors
`tests/evaluation/deepeval/test_combined_evaluation.py` exactly, extended
to four frameworks.
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


def _all_four_evaluators() -> list:
    return [
        *DEFAULT_EVALUATORS,
        _FakeEvaluator("ragas_fake", "ragas"),
        _FakeEvaluator("deepeval_fake", "deepeval"),
        _FakeEvaluator("openai_evals_fake", "openai_evals"),
    ]


def _one_case() -> EvaluationCase:
    return EvaluationCase(id="case-1", name="n", category="answer", query="hello")


def test_all_four_frameworks_contribute_metric_results_by_default():
    case = _one_case()
    runner = EvaluationRunner(evaluators=_all_four_evaluators())

    _, results = runner.run(_dataset([case]), _fixtures_for("case-1"))
    [result] = results

    assert {m.framework for m in result.metric_results} == {
        "deterministic",
        "ragas",
        "deepeval",
        "openai_evals",
    }


def test_frameworks_filter_can_select_openai_evals_alone():
    case = _one_case()
    runner = EvaluationRunner(evaluators=_all_four_evaluators())

    _, results = runner.run(_dataset([case]), _fixtures_for("case-1"), frameworks={"openai_evals"})
    [result] = results

    assert {m.framework for m in result.metric_results} == {"openai_evals"}


def test_frameworks_filter_can_exclude_openai_evals():
    case = _one_case()
    runner = EvaluationRunner(evaluators=_all_four_evaluators())

    _, results = runner.run(
        _dataset([case]),
        _fixtures_for("case-1"),
        frameworks={"deterministic", "ragas", "deepeval"},
    )
    [result] = results

    assert "openai_evals" not in {m.framework for m in result.metric_results}
