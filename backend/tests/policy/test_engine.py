"""Sprint 8's required test list, verbatim: PASS, WARN, BLOCK, critical
block, regression block, latency block, cost block, evaluator failure,
zero-evaluator execution, required evaluator disabled/unavailable, and
optional evaluator disabled - each has at least one dedicated test below.
"""

from app.domain.baseline import Baseline
from app.domain.case_result import CaseResult
from app.domain.enums import GateStatus
from app.domain.evaluation_run import EvaluationRun
from app.domain.metric_result import MetricResult
from app.domain.release_policy import ReleasePolicy, RequiredMetricPolicy
from app.policy.engine import PolicyEngine


def _run(**overrides) -> EvaluationRun:
    defaults = {
        "dataset_name": "support_bot",
        "dataset_version": "1.0.0",
        "provider": "deterministic",
        "model": "fixture-v1",
    }
    defaults.update(overrides)
    return EvaluationRun(**defaults)


def _metric(**overrides) -> MetricResult:
    defaults = {
        "metric_name": "exact_match",
        "score": 1.0,
        "threshold": 1.0,
        "passed": True,
        "framework": "deterministic",
    }
    defaults.update(overrides)
    return MetricResult(**defaults)


def _infra_failure_metric(metric_name: str, framework: str = "ragas") -> MetricResult:
    return MetricResult(
        metric_name=metric_name,
        score=0.0,
        threshold=0.8,
        passed=False,
        framework=framework,
        explanation="infrastructure failure",
        metadata={f"{framework}_status": "infrastructure_error", "error_type": "timeout"},
    )


def _skipped_metric(metric_name: str, framework: str = "ragas") -> MetricResult:
    return MetricResult(
        metric_name=metric_name,
        score=0.0,
        threshold=0.8,
        passed=True,
        framework=framework,
        metadata={f"{framework}_status": "skipped_missing_input"},
    )


def _case(**overrides) -> CaseResult:
    defaults = {
        "case_id": "c1",
        "response": "ok",
        "latency_ms": 100.0,
        "input_tokens": 1,
        "output_tokens": 1,
        "estimated_cost": 0.001,
        "passed": True,
        "metric_results": [],
    }
    defaults.update(overrides)
    return CaseResult(**defaults)


def _policy(**overrides) -> ReleasePolicy:
    defaults = {"name": "p", "version": "1.0.0"}
    defaults.update(overrides)
    return ReleasePolicy(**defaults)


def _baseline(**overrides) -> Baseline:
    defaults = {
        "id": "b1",
        "dataset_name": "support_bot",
        "dataset_version": "1.0.0",
        "version": 1,
        "run_id": "prev-run",
        "pass_rate": 1.0,
        "aggregate_metrics": {},
    }
    defaults.update(overrides)
    return Baseline(**defaults)


ENGINE = PolicyEngine()


class TestPass:
    def test_clean_run_passes(self):
        case = _case(metric_results=[_metric()])
        decision = ENGINE.decide(_run(), [case], _policy())

        assert decision.status == GateStatus.PASS
        assert decision.reasons == []
        assert decision.aggregate_metrics == {"exact_match": 1.0}

    def test_pass_records_audit_fields(self):
        case = _case(metric_results=[_metric()])
        run = _run()
        policy = _policy()
        decision = ENGINE.decide(run, [case], policy)

        assert decision.run_id == run.id
        assert decision.dataset_version == run.dataset_version
        assert decision.provider == run.provider
        assert decision.model == run.model
        assert decision.policy_id == policy.id
        assert decision.policy_version == policy.version


class TestBlockFromMinPassRate:
    def test_pass_rate_below_minimum_blocks(self):
        cases = [
            _case(case_id="c1", passed=True, metric_results=[_metric()]),
            _case(case_id="c2", passed=False, metric_results=[_metric(passed=False, score=0.0)]),
        ]
        policy = _policy(min_pass_rate=1.0)

        decision = ENGINE.decide(_run(), cases, policy)

        assert decision.status == GateStatus.BLOCK
        assert any("pass rate" in r for r in decision.reasons)

    def test_pass_rate_meeting_minimum_passes(self):
        cases = [
            _case(case_id="c1", passed=True, metric_results=[_metric()]),
            _case(case_id="c2", passed=False, metric_results=[_metric(passed=False, score=0.0)]),
        ]
        policy = _policy(min_pass_rate=0.5)

        decision = ENGINE.decide(_run(), cases, policy)

        assert decision.status == GateStatus.PASS


class TestCriticalCaseBlock:
    def test_critical_failure_blocks_by_default(self):
        case = _case(critical_failure=True, metric_results=[_metric()])
        decision = ENGINE.decide(_run(), [case], _policy())

        assert decision.status == GateStatus.BLOCK
        assert decision.critical_failures == ["c1"]
        assert any("critical case" in r for r in decision.reasons)

    def test_critical_failure_warns_when_policy_configured(self):
        case = _case(critical_failure=True, metric_results=[_metric()])
        policy = _policy(critical_case_action="warn", min_pass_rate=0.0)
        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.WARN
        assert decision.critical_failures == ["c1"]


class TestRegressionBlock:
    def test_pass_rate_regression_beyond_tolerance_blocks(self):
        policy = _policy(max_regression_tolerance=0.0, min_pass_rate=0.0)
        baseline = _baseline(pass_rate=1.0)
        # This run's pass rate is 1.0 too (single passing case) - force a
        # regression by lowering the baseline comparison via a failing case.
        cases_regressed = [_case(passed=False, metric_results=[_metric(passed=False, score=0.0)])]

        decision = ENGINE.decide(_run(), cases_regressed, policy, baseline)

        assert decision.status == GateStatus.BLOCK
        assert decision.regression_summary is not None
        assert decision.regression_summary.pass_rate_delta < 0
        assert any("regressed" in r for r in decision.reasons)

    def test_metric_regression_beyond_tolerance_blocks(self):
        case = _case(metric_results=[_metric(metric_name="ragas_faithfulness", score=0.5)])
        policy = _policy(max_regression_tolerance=0.05, min_pass_rate=0.0)
        baseline = _baseline(aggregate_metrics={"ragas_faithfulness": 0.9})

        decision = ENGINE.decide(_run(), [case], policy, baseline)

        assert decision.status == GateStatus.BLOCK
        assert decision.regression_summary.metric_deltas["ragas_faithfulness"] < -0.05

    def test_regression_within_tolerance_does_not_block(self):
        case = _case(metric_results=[_metric(metric_name="ragas_faithfulness", score=0.87)])
        policy = _policy(max_regression_tolerance=0.05, min_pass_rate=0.0)
        baseline = _baseline(aggregate_metrics={"ragas_faithfulness": 0.9})

        decision = ENGINE.decide(_run(), [case], policy, baseline)

        assert decision.status == GateStatus.PASS

    def test_regression_can_warn_instead_of_block(self):
        case = _case(metric_results=[_metric(metric_name="ragas_faithfulness", score=0.5)])
        policy = _policy(max_regression_tolerance=0.05, regression_action="warn", min_pass_rate=0.0)
        baseline = _baseline(aggregate_metrics={"ragas_faithfulness": 0.9})

        decision = ENGINE.decide(_run(), [case], policy, baseline)

        assert decision.status == GateStatus.WARN

    def test_no_baseline_means_no_regression_check(self):
        case = _case(metric_results=[_metric()])
        decision = ENGINE.decide(_run(), [case], _policy(), baseline=None)

        assert decision.regression_summary is None
        assert decision.baseline_version is None
        assert decision.status == GateStatus.PASS

    def test_new_and_recovered_failures_tracked(self):
        # Baseline: metric A was failing (0.5 < 0.8), metric B was passing (0.9 >= 0.8).
        baseline = _baseline(
            aggregate_metrics={"ragas_faithfulness": 0.5, "ragas_context_recall": 0.9}
        )
        # Current run: metric A recovered (0.85), metric B newly fails (0.6).
        case = _case(
            metric_results=[
                _metric(metric_name="ragas_faithfulness", score=0.85),
                _metric(metric_name="ragas_context_recall", score=0.6),
            ]
        )
        policy = _policy(
            min_pass_rate=0.0,
            max_regression_tolerance=1.0,
            required_metrics=[
                RequiredMetricPolicy(metric_name="ragas_faithfulness", min_score=0.8),
                RequiredMetricPolicy(metric_name="ragas_context_recall", min_score=0.8),
            ],
        )

        decision = ENGINE.decide(_run(), [case], policy, baseline)

        assert decision.regression_summary.recovered_failures == ["ragas_faithfulness"]
        assert decision.regression_summary.new_failures == ["ragas_context_recall"]


class TestLatencyBudget:
    def test_latency_over_budget_warns_by_default(self):
        case = _case(latency_ms=5000.0, metric_results=[_metric()])
        policy = _policy(latency_budget_ms=1000.0)

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.WARN
        assert any("latency" in r for r in decision.reasons)

    def test_latency_over_budget_blocks_when_configured(self):
        case = _case(latency_ms=5000.0, metric_results=[_metric()])
        policy = _policy(latency_budget_ms=1000.0, latency_budget_action="block")

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.BLOCK

    def test_latency_within_budget_passes(self):
        case = _case(latency_ms=500.0, metric_results=[_metric()])
        policy = _policy(latency_budget_ms=1000.0)

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.PASS


class TestCostBudget:
    def test_cost_over_budget_warns_by_default(self):
        case = _case(estimated_cost=5.0, metric_results=[_metric()])
        policy = _policy(cost_budget_usd=1.0)

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.WARN
        assert any("cost" in r for r in decision.reasons)

    def test_cost_over_budget_blocks_when_configured(self):
        case = _case(estimated_cost=5.0, metric_results=[_metric()])
        policy = _policy(cost_budget_usd=1.0, cost_budget_action="block")

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.BLOCK


class TestEvaluatorInfrastructureFailure:
    def test_infrastructure_failure_on_required_metric_blocks_by_default(self):
        case = _case(metric_results=[_metric(), _infra_failure_metric("ragas_faithfulness")])
        policy = _policy(required_metrics=[RequiredMetricPolicy(metric_name="ragas_faithfulness")])

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.BLOCK
        assert decision.framework_errors == {"ragas_faithfulness": 1}
        # An infrastructure failure must never show up as a quality score.
        assert "ragas_faithfulness" not in decision.aggregate_metrics
        assert any("infrastructure failure" in r for r in decision.reasons)

    def test_infrastructure_failure_can_warn_instead_of_block(self):
        case = _case(metric_results=[_metric(), _infra_failure_metric("ragas_faithfulness")])
        policy = _policy(
            required_metrics=[
                RequiredMetricPolicy(
                    metric_name="ragas_faithfulness", on_infrastructure_failure="warn"
                )
            ]
        )

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.WARN

    def test_infrastructure_failure_can_be_ignored(self):
        case = _case(metric_results=[_metric(), _infra_failure_metric("ragas_faithfulness")])
        policy = _policy(
            required_metrics=[
                RequiredMetricPolicy(
                    metric_name="ragas_faithfulness", on_infrastructure_failure="ignore"
                )
            ]
        )

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.PASS
        assert decision.reasons == []

    def test_infrastructure_failure_is_distinct_from_a_quality_score_of_zero(self):
        """The whole point of Sprint 5/6/7's error_type convention: an
        infra failure must never be aggregated as if it were a real 0.0
        quality score."""
        case = _case(
            metric_results=[
                _metric(metric_name="ragas_faithfulness", score=0.95),
                _infra_failure_metric("ragas_faithfulness"),
            ]
        )
        decision = ENGINE.decide(_run(), [case], _policy())

        # Only the real scored instance contributes to the aggregate.
        assert decision.aggregate_metrics["ragas_faithfulness"] == 0.95
        assert decision.framework_errors["ragas_faithfulness"] == 1


class TestZeroEvaluatorExecution:
    """The sprint's own explicit sentence: a run must never receive PASS
    merely because zero required evaluators executed."""

    def test_zero_metric_results_anywhere_never_vacuously_passes(self):
        case = _case(metric_results=[])
        decision = ENGINE.decide(_run(), [case], _policy())

        assert decision.status == GateStatus.BLOCK
        assert any("vacuous" in r for r in decision.reasons)

    def test_zero_metric_results_blocks_even_with_no_required_metrics_configured(self):
        """An empty required_metrics policy is a valid, permissive
        configuration - it must not be read as "nothing to check, so
        pass."""
        case = _case(metric_results=[])
        policy = _policy(required_metrics=[])

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.BLOCK

    def test_at_least_one_scored_metric_avoids_the_vacuous_guard(self):
        case = _case(metric_results=[_metric()])
        decision = ENGINE.decide(_run(), [case], _policy())

        assert decision.status == GateStatus.PASS


class TestRequiredEvaluatorDisabledOrUnavailable:
    def test_required_metric_never_executed_blocks_by_default(self):
        case = _case(metric_results=[_metric()])  # exact_match only
        policy = _policy(required_metrics=[RequiredMetricPolicy(metric_name="ragas_faithfulness")])

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.BLOCK
        assert any("did not execute" in r and "ragas_faithfulness" in r for r in decision.reasons)

    def test_required_metric_never_executed_can_warn(self):
        case = _case(metric_results=[_metric()])
        policy = _policy(
            required_metrics=[
                RequiredMetricPolicy(metric_name="ragas_faithfulness", on_missing="warn")
            ]
        )

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.WARN

    def test_required_metric_never_executed_can_be_ignored(self):
        case = _case(metric_results=[_metric()])
        policy = _policy(
            required_metrics=[
                RequiredMetricPolicy(metric_name="ragas_faithfulness", on_missing="ignore")
            ]
        )

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.PASS

    def test_required_metric_only_present_as_skipped_counts_as_not_executed(self):
        """A framework-adapter "skipped_missing_input" result (Sprint 5/6/7)
        is not a real execution for policy purposes - same as never having
        run at all."""
        case = _case(metric_results=[_metric(), _skipped_metric("ragas_context_recall")])
        policy = _policy(
            required_metrics=[RequiredMetricPolicy(metric_name="ragas_context_recall")]
        )

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.BLOCK
        assert "ragas_context_recall" not in decision.aggregate_metrics


class TestOptionalEvaluatorDisabled:
    def test_a_metric_not_named_in_required_metrics_never_affects_status(self):
        """An optional evaluator that's disabled, unavailable, or not
        applicable to any case must not automatically cause BLOCK -
        because nothing in the policy required it."""
        case = _case(metric_results=[_metric()])  # deepeval_criteria simply absent
        policy = _policy()  # required_metrics is empty - nothing is required

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.PASS

    def test_a_low_scoring_metric_that_is_not_required_does_not_block(self):
        case = _case(
            metric_results=[
                _metric(),
                _metric(metric_name="deepeval_criteria", score=0.1, passed=False),
            ]
        )
        policy = _policy()  # deepeval_criteria is not in required_metrics

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.PASS
        assert decision.aggregate_metrics["deepeval_criteria"] == 0.1

    def test_a_skipped_optional_metric_does_not_block(self):
        case = _case(metric_results=[_metric(), _skipped_metric("deepeval_criteria", "deepeval")])
        decision = ENGINE.decide(_run(), [case], _policy())

        assert decision.status == GateStatus.PASS
        assert "deepeval_criteria" not in decision.aggregate_metrics


class TestRequiredMetricAggregateThreshold:
    def test_required_metric_meeting_threshold_passes(self):
        case = _case(metric_results=[_metric(metric_name="ragas_faithfulness", score=0.85)])
        policy = _policy(
            required_metrics=[RequiredMetricPolicy(metric_name="ragas_faithfulness", min_score=0.8)]
        )

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.PASS

    def test_required_metric_below_threshold_always_blocks(self):
        """Unlike on_missing/on_infrastructure_failure, a real quality-
        threshold miss on a required metric has no "warn"/"ignore" option -
        see DECISIONS.md #28."""
        case = _case(metric_results=[_metric(metric_name="ragas_faithfulness", score=0.5)])
        policy = _policy(
            required_metrics=[RequiredMetricPolicy(metric_name="ragas_faithfulness", min_score=0.8)]
        )

        decision = ENGINE.decide(_run(), [case], policy)

        assert decision.status == GateStatus.BLOCK
        assert any("below the required minimum" in r for r in decision.reasons)
