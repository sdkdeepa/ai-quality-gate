from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.deps import get_policy_service
from app.domain.release_policy import ReleasePolicy, RequiredMetricPolicy
from app.services.policy_service import PolicyService

router = APIRouter(prefix="/gate", tags=["gate"])


class RunGateRequest(BaseModel):
    run_id: str
    # None (default) uses whichever policy is currently active (the most
    # recently registered one) - see PolicyRepository.get_active.
    policy_id: str | None = None


class ApproveBaselineRequest(BaseModel):
    run_id: str
    approved_by: str | None = None
    notes: str | None = None


class CreatePolicyRequest(BaseModel):
    name: str
    version: str
    required_metrics: list[RequiredMetricPolicy] = []
    min_pass_rate: float = 1.0
    critical_case_action: Literal["block", "warn"] = "block"
    max_regression_tolerance: float = 0.0
    regression_action: Literal["block", "warn"] = "block"
    latency_budget_ms: float | None = None
    latency_budget_action: Literal["block", "warn"] = "warn"
    cost_budget_usd: float | None = None
    cost_budget_action: Literal["block", "warn"] = "warn"


@router.post("/decisions")
def run_gate(
    request: RunGateRequest,
    policy_service: Annotated[PolicyService, Depends(get_policy_service)],
):
    """Requirement #8 "run gate": evaluates an already-completed
    evaluation run (`POST /evaluations/runs` first) against a release
    policy and persists the resulting GateDecision. Compares against the
    dataset's latest approved baseline automatically, if one exists."""
    return policy_service.decide(request.run_id, request.policy_id)


@router.get("/decisions/{decision_id}")
def get_decision(
    decision_id: str,
    policy_service: Annotated[PolicyService, Depends(get_policy_service)],
):
    """Requirement #8 "inspect decisions"."""
    return policy_service.get_decision(decision_id)


@router.get("/decisions")
def list_decisions(
    policy_service: Annotated[PolicyService, Depends(get_policy_service)],
    run_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
):
    """Requirement #8 "list history". Filter to one run's decisions with
    `run_id`, or omit it for the most recent decisions across all runs."""
    if run_id is not None:
        return policy_service.list_for_run(run_id)
    return policy_service.list_history(limit)


@router.post("/baselines")
def approve_baseline(
    request: ApproveBaselineRequest,
    policy_service: Annotated[PolicyService, Depends(get_policy_service)],
):
    """Requirement #8 "approve baseline": snapshots a run's aggregate
    metrics and pass rate as the new approved baseline for its dataset,
    auto-versioned (1, 2, 3, ...) per dataset name."""
    return policy_service.approve_baseline(
        request.run_id, approved_by=request.approved_by, notes=request.notes
    )


@router.get("/baselines")
def list_baselines(
    policy_service: Annotated[PolicyService, Depends(get_policy_service)],
    dataset_name: str | None = None,
):
    return policy_service.list_baselines(dataset_name)


@router.get("/compare")
def compare_runs(
    policy_service: Annotated[PolicyService, Depends(get_policy_service)],
    run_id_a: str,
    run_id_b: str,
):
    """Requirement #8 "compare runs": a direct aggregate-metric/pass-rate
    diff between any two runs, independent of policy or baseline approval."""
    return policy_service.compare_runs(run_id_a, run_id_b)


@router.post("/policies")
def create_policy(
    request: CreatePolicyRequest,
    policy_service: Annotated[PolicyService, Depends(get_policy_service)],
):
    """Registers a new release policy, which immediately becomes active
    (the most recently registered policy is always the active one - see
    PolicyRepository.get_active)."""
    policy = ReleasePolicy(**request.model_dump())
    return policy_service.register_policy(policy)


@router.get("/policies/active")
def get_active_policy(
    policy_service: Annotated[PolicyService, Depends(get_policy_service)],
):
    return policy_service.get_active_policy()


@router.get("/policies/{policy_id}")
def get_policy(
    policy_id: str,
    policy_service: Annotated[PolicyService, Depends(get_policy_service)],
):
    return policy_service.get_policy(policy_id)


@router.get("/policies")
def list_policies(
    policy_service: Annotated[PolicyService, Depends(get_policy_service)],
):
    return policy_service.list_policies()
