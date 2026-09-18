"""Orchestrates the Release Policy Engine for the API layer: resolves an
evaluation run's stored `CaseResult`s, the active (or a named) policy, and
the dataset's latest approved baseline (if any), calls `PolicyEngine`, and
persists the result. Also owns baseline approval and the run-vs-run
comparison utility (requirement #8's five API capabilities all route
through this one service).
"""

from app.core.exceptions import NotFoundError
from app.domain.baseline import Baseline
from app.domain.evaluation_run import EvaluationRun
from app.domain.gate_decision import GateDecision
from app.domain.release_policy import ReleasePolicy
from app.policy.engine import PolicyEngine, aggregate_metrics_for_run, pass_rate_for_run
from app.repositories.in_memory import InMemoryCaseResultStore, InMemoryRepository
from app.repositories.sqlite import BaselineRepository, GateDecisionRepository, PolicyRepository


class PolicyService:
    def __init__(
        self,
        run_repository: InMemoryRepository[EvaluationRun],
        case_result_store: InMemoryCaseResultStore,
        policy_repository: PolicyRepository,
        baseline_repository: BaselineRepository,
        gate_decision_repository: GateDecisionRepository,
        engine: PolicyEngine | None = None,
    ) -> None:
        self._run_repository = run_repository
        self._case_result_store = case_result_store
        self._policy_repository = policy_repository
        self._baseline_repository = baseline_repository
        self._gate_decision_repository = gate_decision_repository
        self._engine = engine or PolicyEngine()

    def _get_run_and_results(self, run_id: str):
        run = self._run_repository.get(run_id)
        if run is None:
            raise NotFoundError(f"no evaluation run {run_id!r}")
        results = self._case_result_store.get(run.id) or []
        return run, results

    def _resolve_policy(self, policy_id: str | None) -> ReleasePolicy:
        if policy_id is not None:
            policy = self._policy_repository.get(policy_id)
            if policy is None:
                raise NotFoundError(f"no release policy {policy_id!r}")
            return policy
        policy = self._policy_repository.get_active()
        if policy is None:
            raise NotFoundError(
                "no release policy is registered - POST /api/v1/gate/policies first"
            )
        return policy

    def decide(self, run_id: str, policy_id: str | None = None) -> GateDecision:
        run, case_results = self._get_run_and_results(run_id)
        policy = self._resolve_policy(policy_id)
        baseline = self._baseline_repository.get_latest_for_dataset(run.dataset_name)
        decision = self._engine.decide(run, case_results, policy, baseline)
        self._gate_decision_repository.add(decision)
        return decision

    def get_decision(self, decision_id: str) -> GateDecision:
        decision = self._gate_decision_repository.get(decision_id)
        if decision is None:
            raise NotFoundError(f"no gate decision {decision_id!r}")
        return decision

    def list_history(self, limit: int = 50) -> list[GateDecision]:
        return self._gate_decision_repository.list_history(limit)

    def list_for_run(self, run_id: str) -> list[GateDecision]:
        return self._gate_decision_repository.list_for_run(run_id)

    def approve_baseline(
        self, run_id: str, *, approved_by: str | None = None, notes: str | None = None
    ) -> Baseline:
        run, case_results = self._get_run_and_results(run_id)
        return self._baseline_repository.approve(
            dataset_name=run.dataset_name,
            dataset_version=run.dataset_version,
            run_id=run.id,
            pass_rate=pass_rate_for_run(case_results),
            aggregate_metrics=aggregate_metrics_for_run(case_results),
            approved_by=approved_by,
            notes=notes,
        )

    def list_baselines(self, dataset_name: str | None = None) -> list[Baseline]:
        if dataset_name is not None:
            return self._baseline_repository.list_for_dataset(dataset_name)
        return self._baseline_repository.list()

    def compare_runs(self, run_id_a: str, run_id_b: str) -> dict:
        """Direct aggregate-metric/pass-rate diff between two runs,
        independent of any policy or approved baseline (requirement #8's
        "compare runs" — a general inspection tool, distinct from
        `decide()`'s baseline-driven regression check)."""
        run_a, results_a = self._get_run_and_results(run_id_a)
        run_b, results_b = self._get_run_and_results(run_id_b)

        metrics_a = aggregate_metrics_for_run(results_a)
        metrics_b = aggregate_metrics_for_run(results_b)
        shared = set(metrics_a) & set(metrics_b)

        return {
            "run_a": run_a,
            "run_b": run_b,
            "pass_rate_a": pass_rate_for_run(results_a),
            "pass_rate_b": pass_rate_for_run(results_b),
            "aggregate_metrics_a": metrics_a,
            "aggregate_metrics_b": metrics_b,
            "metric_deltas": {name: metrics_b[name] - metrics_a[name] for name in sorted(shared)},
        }

    def register_policy(self, policy: ReleasePolicy) -> ReleasePolicy:
        return self._policy_repository.add(policy)

    def get_active_policy(self) -> ReleasePolicy:
        policy = self._policy_repository.get_active()
        if policy is None:
            raise NotFoundError("no release policy is registered")
        return policy

    def get_policy(self, policy_id: str) -> ReleasePolicy:
        policy = self._policy_repository.get(policy_id)
        if policy is None:
            raise NotFoundError(f"no release policy {policy_id!r}")
        return policy

    def list_policies(self) -> list[ReleasePolicy]:
        return self._policy_repository.list()
