"""M4 parity: the evidence policy agrees with the server's PolicyEngine.

Each scenario feeds the same real case results (the M0 datasets, and the M3
mixed run from the real runner and RAGAS evaluator) to both engines:
PolicyEngine directly, and the evidence policy through the M3 adapter. The
two policies in a scenario express the same rules:

    PolicyEngine                              EvidencePolicy
    min_pass_rate=1.0 (any failed case)       failed and error checks block (defaults)
    a skipped metric counts as passed         on_optional_skipped="ignore"
    required metric on_missing                required "*::<metric>" with on_missing
    required metric on_infrastructure_failure required "*::<metric>" with on_error
    zero metrics executed -> BLOCK            no check passed or failed -> BLOCK

The server keeps using PolicyEngine; these tests catch drift between the two.
Rules where they differ on purpose are in the last section.
"""

import pytest

from app.domain.enums import GateStatus as ServerGateStatus
from app.domain.release_policy import ReleasePolicy
from app.policy.engine import PolicyEngine
from aqg.adapters import evidence_from_llm_run
from aqg.policy import EvidencePolicy, GateStatus, decide
from tests.aqg.test_llm_adapter import _m0_run, _mixed_run

SERVER_DEFAULT = {}
EVIDENCE_DEFAULT = {"on_optional_skipped": "ignore"}


def _both(run, cases, server_policy: dict, evidence_policy: dict) -> tuple[str, str]:
    server = PolicyEngine().decide(
        run, cases, ReleasePolicy(name="parity", version="1", **server_policy)
    )
    evidence = decide(evidence_from_llm_run(run, cases), EvidencePolicy(**evidence_policy))
    return server.status.value, evidence.status.value


def _subset(source, keep):
    run, cases = source
    return run, [c for c in cases if keep(c)]


def _required(metric: str, **actions) -> dict:
    return {"required_metrics": [{"metric_name": metric, **actions}]}


def _evidence_required(metric: str, **actions) -> dict:
    return {**EVIDENCE_DEFAULT, "required": [f"*::{metric}"], **actions}


def test_gate_status_values_are_the_servers():
    assert [s.value for s in GateStatus] == [s.value for s in ServerGateStatus]


# --- M0 datasets ------------------------------------------------------------------------


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
def test_m0_full_runs_block_in_both(version):
    run, cases = _m0_run(version)
    assert _both(run, cases, SERVER_DEFAULT, EVIDENCE_DEFAULT) == ("block", "block")


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
def test_m0_passing_cases_pass_in_both(version):
    run, cases = _subset(_m0_run(version), lambda c: c.passed)
    assert cases
    assert _both(run, cases, SERVER_DEFAULT, EVIDENCE_DEFAULT) == ("pass", "pass")


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
def test_m0_failed_cases_block_in_both(version):
    run, cases = _subset(_m0_run(version), lambda c: not c.passed)
    assert _both(run, cases, SERVER_DEFAULT, EVIDENCE_DEFAULT) == ("block", "block")


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
@pytest.mark.parametrize("action", ["block", "warn", "ignore"])
def test_m0_required_metric_that_never_ran(version, action):
    run, cases = _subset(_m0_run(version), lambda c: c.passed)
    server = _required("ragas_faithfulness", on_missing=action)
    evidence = _evidence_required("ragas_faithfulness", on_missing=action)
    expected = {"block": "block", "warn": "warn", "ignore": "pass"}[action]
    assert _both(run, cases, server, evidence) == (expected, expected)


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0"])
def test_m0_required_metric_that_ran_and_passed(version):
    run, cases = _subset(_m0_run(version), lambda c: c.passed)
    metric = cases[0].metric_results[0].metric_name
    assert _both(run, cases, _required(metric), _evidence_required(metric)) == ("pass", "pass")


# --- M3 mixed run: skipped, error, crash and unreachable cases ---------------------------


def _mixed(*case_ids: str):
    return _subset(_mixed_run(), lambda c: c.case_id in case_ids)


@pytest.mark.parametrize(
    ("case_ids", "expected"),
    [
        (("grounded",), "pass"),
        (("grounded", "no-context"), "pass"),  # a skipped metric doesn't fail the case
        (("grounded", "ungrounded"), "block"),  # a quality failure, on a critical case
        (("grounded", "judge-down"), "block"),  # an evaluator infrastructure failure
        (("grounded", "evaluator-crash"), "block"),  # a crashed evaluator, isolated
        (("unreachable",), "block"),  # nothing was evaluated at all
        (("grounded", "unreachable"), "block"),  # the system under test was down for a case
    ],
)
def test_mixed_run_default_policy(case_ids, expected):
    run, cases = _mixed(*case_ids)
    assert _both(run, cases, SERVER_DEFAULT, EVIDENCE_DEFAULT) == (expected, expected)


@pytest.mark.parametrize("action", ["block", "warn", "ignore"])
def test_mixed_run_required_metric_with_infrastructure_failure(action):
    run, cases = _mixed("grounded", "judge-down")
    server = {
        "min_pass_rate": 0.0,
        **_required("ragas_faithfulness", on_infrastructure_failure=action),
    }
    evidence = _evidence_required("ragas_faithfulness", on_error=action)
    expected = {"block": "block", "warn": "warn", "ignore": "pass"}[action]
    assert _both(run, cases, server, evidence) == (expected, expected)


def test_mixed_run_optional_crash_ignored_in_both():
    run, cases = _mixed("grounded", "evaluator-crash")
    server = {"min_pass_rate": 0.0}
    evidence = {**EVIDENCE_DEFAULT, "on_optional_error": "ignore"}
    assert _both(run, cases, server, evidence) == ("pass", "pass")


def test_mixed_run_required_metric_skipped_everywhere_blocks_in_both():
    # PolicyEngine treats "every instance skipped" as missing (on_missing);
    # the evidence policy reports it through on_skipped.
    run, cases = _mixed("no-context")
    server = _required("ragas_faithfulness", on_missing="block")
    evidence = _evidence_required("ragas_faithfulness", on_skipped="block")
    assert _both(run, cases, server, evidence) == ("block", "block")


# --- where the two differ on purpose (approved decisions) ---------------------------------


def test_difference_empty_run():
    """Decision 7: incomplete evidence never passes. PolicyEngine passes a run
    with no case results at all; the evidence policy blocks it."""
    run, _ = _m0_run("1.0.0")
    assert _both(run, [], SERVER_DEFAULT, EVIDENCE_DEFAULT) == ("pass", "block")


def test_difference_required_metric_skipped_on_some_cases():
    """Decision 6: a required check that is skipped blocks. PolicyEngine only
    treats a required metric as missing when no case scored it."""
    run, cases = _mixed("grounded", "no-context")
    server = _required("ragas_faithfulness")
    evidence = _evidence_required("ragas_faithfulness")
    assert _both(run, cases, server, evidence) == ("pass", "block")


def test_difference_run_where_every_metric_was_skipped():
    """Plan rule: zero executed checks is always BLOCK. PolicyEngine's guard
    counts skipped metric results as results, so a run where every metric was
    skipped only gets the required metric's on_missing action (here WARN)."""
    run, cases = _mixed("no-context")
    server = _required("ragas_faithfulness", on_missing="warn")
    evidence = _evidence_required("ragas_faithfulness", on_skipped="warn")
    assert _both(run, cases, server, evidence) == ("warn", "block")


def test_difference_required_metric_failing_one_case():
    """A failed required check always blocks. PolicyEngine only blocks a
    required metric on its aggregate min_score, or through min_pass_rate."""
    run, cases = _mixed("grounded", "ungrounded")
    server = {
        "min_pass_rate": 0.0,
        "critical_case_action": "warn",
        **_required("ragas_faithfulness"),
    }
    evidence = _evidence_required("ragas_faithfulness")
    assert _both(run, cases, server, evidence) == ("warn", "block")
