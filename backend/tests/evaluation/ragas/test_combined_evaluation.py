"""Sprint 5 requirement #7/#9: a RAG case run through EvaluationRunner
produces BOTH deterministic and RAGAS MetricResults, without any change to
EvaluationRunner itself or to how deterministic-only cases behave.

Uses a fake Evaluator standing in for the real RAGAS ones (no ragas/openai
imports here) - the combined-evaluation behavior being tested is entirely
`EvaluationRunner`'s, which only depends on the `Evaluator` protocol.
"""

from datetime import UTC, datetime

from app.domain.evaluation_case import EvaluationCase
from app.domain.golden_dataset import GoldenDataset
from app.evaluation.deterministic import DEFAULT_EVALUATORS
from app.evaluation.runner import EvaluationRunner
from app.evaluation.types import FixtureResponse


class _FakeRagasEvaluator:
    """Minimal Evaluator protocol implementation, framework='ragas'."""

    name = "ragas_fake_metric"

    def __init__(self, score: float, threshold: float = 0.7) -> None:
        self._score = score
        self._threshold = threshold

    def applies_to(self, case: EvaluationCase) -> bool:
        return case.category == "rag"

    def evaluate(self, evaluation_input):
        from app.domain.metric_result import MetricResult

        return MetricResult(
            metric_name=self.name,
            score=self._score,
            threshold=self._threshold,
            passed=self._score >= self._threshold,
            framework="ragas",
            metadata={"ragas_status": "scored"},
        )


def _dataset(cases: list[EvaluationCase]) -> GoldenDataset:
    return GoldenDataset(
        name="test_dataset",
        version="1.0.0",
        created_at=datetime.now(UTC),
        description="A test dataset.",
        cases=cases,
    )


def test_rag_case_gets_both_deterministic_and_ragas_metric_results():
    case = EvaluationCase(
        id="rag-1",
        name="n",
        category="rag",
        query="What is the warranty length?",
        expected_answer="1-year",
        reference_context=["Electronics have a 1-year warranty."],
        metadata={"required_phrases": ["1-year"]},
    )
    dataset = _dataset([case])
    fixtures = {
        "rag-1": FixtureResponse(
            response="It's a 1-year warranty.",
            retrieved_context=["Electronics have a 1-year warranty."],
            latency_ms=100.0,
            input_tokens=5,
            output_tokens=5,
            estimated_cost=0.001,
        )
    }
    evaluators = list(DEFAULT_EVALUATORS) + [_FakeRagasEvaluator(score=0.9)]
    runner = EvaluationRunner(evaluators=evaluators)

    _, results = runner.run(dataset, fixtures)
    [result] = results

    frameworks = {m.framework for m in result.metric_results}
    assert frameworks == {"deterministic", "ragas"}
    assert result.passed is True


def test_non_rag_case_only_gets_deterministic_results_ragas_evaluator_still_present():
    case = EvaluationCase(
        id="plain-1",
        name="n",
        category="answer",
        query="What is 2+2?",
        expected_answer="4",
        metadata={"match_mode": "exact"},
    )
    dataset = _dataset([case])
    fixtures = {
        "plain-1": FixtureResponse(
            response="4",
            latency_ms=100.0,
            input_tokens=5,
            output_tokens=5,
            estimated_cost=0.001,
        )
    }
    evaluators = list(DEFAULT_EVALUATORS) + [_FakeRagasEvaluator(score=0.9)]
    runner = EvaluationRunner(evaluators=evaluators)

    _, results = runner.run(dataset, fixtures)
    [result] = results

    frameworks = {m.framework for m in result.metric_results}
    assert frameworks == {"deterministic"}


def test_existing_deterministic_only_behavior_is_unchanged_without_ragas_evaluators():
    """Same case/fixture as above, but with the plain DEFAULT_EVALUATORS
    list (Sprint 4 behavior) - proves adding RAGAS support did not change
    what a deterministic-only run produces."""
    case = EvaluationCase(
        id="rag-1",
        name="n",
        category="rag",
        query="What is the warranty length?",
        expected_answer="1-year",
        reference_context=["Electronics have a 1-year warranty."],
        metadata={"required_phrases": ["1-year"]},
    )
    dataset = _dataset([case])
    fixtures = {
        "rag-1": FixtureResponse(
            response="It's a 1-year warranty.",
            retrieved_context=["Electronics have a 1-year warranty."],
            latency_ms=100.0,
            input_tokens=5,
            output_tokens=5,
            estimated_cost=0.001,
        )
    }
    runner = EvaluationRunner()  # DEFAULT_EVALUATORS only, same as Sprint 4

    _, results = runner.run(dataset, fixtures)
    [result] = results

    frameworks = {m.framework for m in result.metric_results}
    assert frameworks == {"deterministic"}
    assert result.passed is True
