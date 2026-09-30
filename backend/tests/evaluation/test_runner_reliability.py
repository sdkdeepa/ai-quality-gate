import time
from datetime import UTC, datetime

from app.domain.enums import RunStatus
from app.domain.evaluation_case import EvaluationCase
from app.domain.golden_dataset import GoldenDataset
from app.domain.metric_result import MetricResult
from app.evaluation.runner import EvaluationRunner
from app.evaluation.types import FixtureResponse
from app.providers.types import ProviderRequest, ProviderResponse


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
        "latency_ms": 1.0,
        "input_tokens": 1,
        "output_tokens": 1,
        "estimated_cost": 0.0,
    }
    defaults.update(overrides)
    return FixtureResponse(**defaults)


class _HangingEvaluator:
    """Never returns within any reasonable timeout - simulates a library
    bug or a pathological input that hangs for a non-network reason (so
    a provider/HTTP-client-level timeout wouldn't help)."""

    name = "hanging_eval"
    framework = "test"

    def applies_to(self, case: EvaluationCase) -> bool:
        return True

    def evaluate(self, evaluation_input):
        time.sleep(30)
        raise AssertionError("should never reach here in these tests")


class _CrashingEvaluator:
    name = "crashing_eval"
    framework = "test"

    def applies_to(self, case: EvaluationCase) -> bool:
        return True

    def evaluate(self, evaluation_input):
        raise RuntimeError("a genuine bug in this evaluator")


class _GoodEvaluator:
    name = "good_eval"
    framework = "test"

    def applies_to(self, case: EvaluationCase) -> bool:
        return True

    def evaluate(self, evaluation_input):
        return MetricResult(
            metric_name="good_eval", score=1.0, threshold=1.0, passed=True, framework="test"
        )


class _CrashingProvider:
    """Simulates a bug in a Provider implementation itself - beyond the
    normalized ProviderError contract, an actual raised exception."""

    name = "crashing_provider"
    model = "does-not-matter"

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        raise RuntimeError("a genuine bug in this provider")


def _one_case(case_id: str = "c1") -> EvaluationCase:
    return EvaluationCase(id=case_id, name="n", category="answer", query="hi", metadata={})


class TestEvaluatorTimeout:
    def test_a_hanging_evaluator_does_not_block_the_whole_run(self):
        case = _one_case()
        runner = EvaluationRunner(evaluators=[_HangingEvaluator()], evaluator_timeout_seconds=0.2)

        start = time.perf_counter()
        run, results = runner.run(_dataset([case]), {"c1": _fixture()})
        elapsed = time.perf_counter() - start

        assert elapsed < 5.0  # nowhere near the evaluator's 30s sleep
        assert results[0].metric_results[0].metadata["error_type"] == "timeout"
        assert results[0].metric_results[0].passed is False

    def test_a_timed_out_evaluator_does_not_stop_other_evaluators_from_running(self):
        case = _one_case()
        runner = EvaluationRunner(
            evaluators=[_HangingEvaluator(), _GoodEvaluator()], evaluator_timeout_seconds=0.2
        )

        _, results = runner.run(_dataset([case]), {"c1": _fixture()})

        names_and_status = {m.metric_name: m.passed for m in results[0].metric_results}
        assert names_and_status["hanging_eval"] is False
        assert names_and_status["good_eval"] is True  # ran successfully despite the timeout

    def test_no_timeout_configured_means_no_timeout_behavior_at_all(self):
        """evaluator_timeout_seconds=None (the default) must behave
        exactly like every pre-Sprint-12 caller/test - a slow evaluator
        just takes as long as it takes."""
        case = _one_case()
        runner = EvaluationRunner(evaluators=[_GoodEvaluator()])  # no timeout kwarg

        _, results = runner.run(_dataset([case]), {"c1": _fixture()})

        assert results[0].metric_results[0].passed is True
        assert results[0].partial is False


class TestEvaluatorFailureIsolation:
    def test_a_crashing_evaluator_does_not_stop_other_evaluators_for_the_same_case(self):
        case = _one_case()
        runner = EvaluationRunner(evaluators=[_CrashingEvaluator(), _GoodEvaluator()])

        _, results = runner.run(_dataset([case]), {"c1": _fixture()})

        names_and_status = {m.metric_name: m.passed for m in results[0].metric_results}
        assert names_and_status["crashing_eval"] is False
        assert names_and_status["good_eval"] is True

    def test_a_crashing_evaluator_produces_an_infrastructure_error_metric_result(self):
        case = _one_case()
        runner = EvaluationRunner(evaluators=[_CrashingEvaluator()])

        _, results = runner.run(_dataset([case]), {"c1": _fixture()})

        crashed = results[0].metric_results[0]
        assert crashed.metadata["error_type"] == "unavailable"
        assert "a genuine bug in this evaluator" in crashed.explanation

    def test_multiple_cases_each_get_isolated_evaluator_failures_independently(self):
        cases = [_one_case("c1"), _one_case("c2")]
        runner = EvaluationRunner(evaluators=[_CrashingEvaluator(), _GoodEvaluator()])

        _, results = runner.run(_dataset(cases), {"c1": _fixture(), "c2": _fixture()})

        for case_result in results:
            names = {m.metric_name: m.passed for m in case_result.metric_results}
            assert names["good_eval"] is True


class TestPartialEvaluationSemantics:
    def test_case_is_marked_partial_when_an_evaluator_crashes(self):
        case = _one_case()
        runner = EvaluationRunner(evaluators=[_CrashingEvaluator(), _GoodEvaluator()])

        _, results = runner.run(_dataset([case]), {"c1": _fixture()})

        assert results[0].partial is True

    def test_case_is_not_marked_partial_when_every_evaluator_succeeds(self):
        case = _one_case()
        runner = EvaluationRunner(evaluators=[_GoodEvaluator()])

        _, results = runner.run(_dataset([case]), {"c1": _fixture()})

        assert results[0].partial is False

    def test_run_status_is_partial_when_any_case_is_partial(self):
        case = _one_case()
        runner = EvaluationRunner(evaluators=[_CrashingEvaluator()])

        run, _ = runner.run(_dataset([case]), {"c1": _fixture()})

        assert run.status == RunStatus.PARTIAL

    def test_run_status_is_completed_when_no_case_is_partial(self):
        case = _one_case()
        runner = EvaluationRunner(evaluators=[_GoodEvaluator()])

        run, _ = runner.run(_dataset([case]), {"c1": _fixture()})

        assert run.status == RunStatus.COMPLETED


class TestPerCaseIsolation:
    def test_one_case_crashing_at_the_provider_level_does_not_lose_other_cases_results(self):
        """The outermost isolation boundary: even a totally unexpected
        exception from Provider.generate() itself (not the normalized
        ProviderError contract) must not lose every other case's already-
        computed results for the same run."""
        cases = [_one_case("c1"), _one_case("c2")]
        runner = EvaluationRunner(evaluators=[_GoodEvaluator()])

        run, results = runner.run_with_provider(_dataset(cases), _CrashingProvider())

        assert len(results) == 2
        assert all(r.error is not None for r in results)
        assert all(r.partial for r in results)
        assert run.status == RunStatus.PARTIAL
