"""The Quality Gate's own release-policy engine.

This is the ONLY place PASS/WARN/BLOCK is ever computed. Every evaluation
framework (deterministic, RAGAS, DeepEval, the OpenAI-Evals-concept
adapters) only ever produces normalized `MetricResult`s — none of them has
any notion of a release decision, a policy, or a baseline. `PolicyEngine`
consumes those `MetricResult`s (via `CaseResult`) plus a `ReleasePolicy` and
an optional `Baseline`, and produces one auditable `GateDecision`. See
DECISIONS.md #28 for the full design rationale, including why several
checks are hard-BLOCK-only (min_pass_rate, a required metric failing its
own quality bar) while others are policy-configurable (critical case
handling, regression, latency/cost budgets).
"""

from collections import defaultdict
from statistics import mean
from typing import Literal

from app.domain.baseline import Baseline
from app.domain.case_result import CaseResult
from app.domain.enums import GateStatus
from app.domain.evaluation_run import EvaluationRun
from app.domain.gate_decision import GateDecision, RegressionSummary
from app.domain.metric_result import MetricResult
from app.domain.release_policy import ReleasePolicy, RequiredMetricPolicy

MetricStatus = Literal["scored", "skipped", "infrastructure_error"]


def _metric_status(metric: MetricResult) -> MetricStatus:
    """Classifies one MetricResult without needing to know which framework
    produced it. Every framework adapter (RAGAS/DeepEval/OpenAI-Evals-
    concept, Sprint 5/6/7) sets `metadata["error_type"]` on an
    infrastructure failure and a `metadata["<framework>_status"] ==
    "skipped_missing_input"` on a not-applicable-for-this-case result;
    deterministic evaluators (Sprint 1-4) never produce either, and are
    always "scored" when present at all - they simply aren't in
    `metric_results` when not applicable, which is a "not present" case
    handled by the caller, not by this function.
    """
    if "error_type" in metric.metadata:
        return "infrastructure_error"
    status_value = next((v for k, v in metric.metadata.items() if k.endswith("_status")), None)
    if status_value == "skipped_missing_input":
        return "skipped"
    return "scored"


def aggregate_metrics_for_run(case_results: list[CaseResult]) -> dict[str, float]:
    """Mean score per metric_name, across every "scored" (not skipped, not
    an infrastructure failure) instance of that metric anywhere in the run.
    Public (not engine-private) because `PolicyService` needs the exact
    same computation to approve a baseline and to compare two runs
    directly, without going through a `ReleasePolicy` at all.
    """
    scores_by_metric: dict[str, list[float]] = defaultdict(list)
    for case in case_results:
        for metric in case.metric_results:
            if _metric_status(metric) == "scored":
                scores_by_metric[metric.metric_name].append(metric.score)
    return {name: mean(scores) for name, scores in scores_by_metric.items() if scores}


def framework_errors_for_run(case_results: list[CaseResult]) -> dict[str, int]:
    """metric_name -> count of infrastructure-failure instances, across
    the whole run. Deliberately never folded into `aggregate_metrics_for_run` -
    see GateDecision.framework_errors' docstring."""
    counts: dict[str, int] = defaultdict(int)
    for case in case_results:
        for metric in case.metric_results:
            if _metric_status(metric) == "infrastructure_error":
                counts[metric.metric_name] += 1
    return dict(counts)


def pass_rate_for_run(case_results: list[CaseResult]) -> float:
    total = len(case_results)
    if not total:
        return 1.0
    passed = sum(1 for c in case_results if c.passed)
    return passed / total


class PolicyEngine:
    """Stateless: every method takes everything it needs as arguments, and
    returns a `GateDecision` it does not persist. Persisting decisions,
    baselines, and policies is `PolicyService`'s job (`app/services/policy_service.py`)."""

    def decide(
        self,
        run: EvaluationRun,
        case_results: list[CaseResult],
        policy: ReleasePolicy,
        baseline: Baseline | None = None,
    ) -> GateDecision:
        blocking_reasons: list[str] = []
        warning_reasons: list[str] = []

        aggregate_metrics = aggregate_metrics_for_run(case_results)
        framework_errors = framework_errors_for_run(case_results)
        critical_failures = [c.case_id for c in case_results if c.critical_failure]

        # --- Vacuous-PASS guard (unconditional, independent of policy
        # configuration): a run that produced not a single scored metric
        # anywhere must never PASS just because nothing was configured as
        # "required." This is the literal "zero required evaluators
        # executed" case from the sprint spec, generalized to "zero
        # evaluators executed at all," since an empty `required_metrics`
        # policy is itself a valid (if permissive) configuration. ---
        total_metric_instances = sum(len(c.metric_results) for c in case_results)
        if case_results and total_metric_instances == 0:
            blocking_reasons.append(
                "no evaluator produced any result for this run "
                "(refusing a vacuous PASS - see ReleasePolicy.required_metrics)"
            )

        # --- Critical case check ---
        if critical_failures:
            reason = f"critical case(s) failed: {sorted(critical_failures)}"
            if policy.critical_case_action == "block":
                blocking_reasons.append(reason)
            else:
                warning_reasons.append(reason)

        # --- Required metrics check ---
        for required in policy.required_metrics:
            self._check_required_metric(
                required, case_results, aggregate_metrics, blocking_reasons, warning_reasons
            )

        # --- Minimum overall pass rate (always a hard BLOCK) ---
        total = len(case_results)
        passed = sum(1 for c in case_results if c.passed)
        pass_rate = pass_rate_for_run(case_results)
        if pass_rate < policy.min_pass_rate:
            blocking_reasons.append(
                f"pass rate {pass_rate:.2%} is below the required minimum "
                f"{policy.min_pass_rate:.2%} ({passed}/{total} cases passed)"
            )

        # --- Latency / cost budgets ---
        if policy.latency_budget_ms is not None and case_results:
            mean_latency = mean(c.latency_ms for c in case_results)
            if mean_latency > policy.latency_budget_ms:
                reason = (
                    f"mean latency {mean_latency:.0f}ms exceeds budget "
                    f"{policy.latency_budget_ms:.0f}ms"
                )
                (
                    blocking_reasons if policy.latency_budget_action == "block" else warning_reasons
                ).append(reason)
        if policy.cost_budget_usd is not None and case_results:
            total_cost = sum(c.estimated_cost for c in case_results)
            if total_cost > policy.cost_budget_usd:
                reason = (
                    f"total cost ${total_cost:.4f} exceeds budget ${policy.cost_budget_usd:.4f}"
                )
                (
                    blocking_reasons if policy.cost_budget_action == "block" else warning_reasons
                ).append(reason)

        # --- Regression vs baseline ---
        regression_summary = None
        if baseline is not None:
            regression_summary, regression_reasons = self._compare_to_baseline(
                policy, baseline, pass_rate, aggregate_metrics
            )
            if regression_reasons:
                (
                    blocking_reasons if policy.regression_action == "block" else warning_reasons
                ).extend(regression_reasons)

        if blocking_reasons:
            status = GateStatus.BLOCK
        elif warning_reasons:
            status = GateStatus.WARN
        else:
            status = GateStatus.PASS

        return GateDecision(
            run_id=run.id,
            dataset_version=run.dataset_version,
            provider=run.provider,
            model=run.model,
            policy_id=policy.id,
            policy_version=policy.version,
            status=status,
            reasons=[*blocking_reasons, *warning_reasons],
            aggregate_metrics=aggregate_metrics,
            critical_failures=sorted(critical_failures),
            framework_errors=framework_errors,
            regression_summary=regression_summary,
            baseline_version=baseline.version if baseline is not None else None,
        )

    def _check_required_metric(
        self,
        required: RequiredMetricPolicy,
        case_results: list[CaseResult],
        aggregate_metrics: dict[str, float],
        blocking_reasons: list[str],
        warning_reasons: list[str],
    ) -> None:
        instances = [
            m
            for case in case_results
            for m in case.metric_results
            if m.metric_name == required.metric_name
        ]
        statuses = [_metric_status(m) for m in instances]
        has_scored = "scored" in statuses
        has_infra_failure = "infrastructure_error" in statuses

        if not instances or (not has_scored and not has_infra_failure):
            # Either the metric never appeared at all, or every instance
            # that did appear was "skipped" (not applicable to the cases it
            # showed up for) - neither is a real execution, so both are
            # "missing" for policy purposes, not merely absent from the
            # aggregate.
            reason = (
                f"required metric {required.metric_name!r} did not execute in this run "
                "(evaluator disabled, unavailable, or not applicable to any case)"
            )
            self._apply_action(required.on_missing, reason, blocking_reasons, warning_reasons)
            return

        if has_infra_failure:
            reason = (
                f"required metric {required.metric_name!r} had an evaluator "
                "infrastructure failure in this run - not a quality score of 0"
            )
            self._apply_action(
                required.on_infrastructure_failure, reason, blocking_reasons, warning_reasons
            )

        # A real quality-threshold miss on a REQUIRED metric is always a
        # hard BLOCK - see DECISIONS.md #28 for why this one isn't
        # policy-configurable the way on_missing/on_infrastructure_failure are.
        if required.min_score is not None and required.metric_name in aggregate_metrics:
            actual = aggregate_metrics[required.metric_name]
            if actual < required.min_score:
                blocking_reasons.append(
                    f"required metric {required.metric_name!r} aggregate score "
                    f"{actual:.3f} is below the required minimum {required.min_score:.3f}"
                )

    @staticmethod
    def _apply_action(
        action: Literal["block", "warn", "ignore"],
        reason: str,
        blocking_reasons: list[str],
        warning_reasons: list[str],
    ) -> None:
        if action == "block":
            blocking_reasons.append(reason)
        elif action == "warn":
            warning_reasons.append(reason)
        # "ignore" -> intentionally not recorded as a reason at all.

    def _compare_to_baseline(
        self,
        policy: ReleasePolicy,
        baseline: Baseline,
        pass_rate: float,
        aggregate_metrics: dict[str, float],
    ) -> tuple[RegressionSummary, list[str]]:
        reasons: list[str] = []
        pass_rate_delta = pass_rate - baseline.pass_rate
        if -pass_rate_delta > policy.max_regression_tolerance:
            reasons.append(
                f"pass rate regressed by {-pass_rate_delta:.2%} versus baseline "
                f"v{baseline.version} (tolerance {policy.max_regression_tolerance:.2%})"
            )

        thresholds_by_metric = {
            r.metric_name: r.min_score for r in policy.required_metrics if r.min_score is not None
        }

        metric_deltas: dict[str, float] = {}
        new_failures: list[str] = []
        recovered_failures: list[str] = []
        shared_metrics = set(aggregate_metrics) & set(baseline.aggregate_metrics)
        for metric_name in sorted(shared_metrics):
            current = aggregate_metrics[metric_name]
            previous = baseline.aggregate_metrics[metric_name]
            delta = current - previous
            metric_deltas[metric_name] = delta

            if -delta > policy.max_regression_tolerance:
                reasons.append(
                    f"metric {metric_name!r} regressed by {-delta:.3f} versus baseline "
                    f"v{baseline.version} (tolerance {policy.max_regression_tolerance:.3f})"
                )

            threshold = thresholds_by_metric.get(metric_name)
            if threshold is not None:
                was_passing = previous >= threshold
                is_passing = current >= threshold
                if was_passing and not is_passing:
                    new_failures.append(metric_name)
                elif not was_passing and is_passing:
                    recovered_failures.append(metric_name)

        summary = RegressionSummary(
            baseline_version=baseline.version,
            pass_rate_delta=pass_rate_delta,
            metric_deltas=metric_deltas,
            new_failures=new_failures,
            recovered_failures=recovered_failures,
        )
        return summary, reasons
