"""LLM adapter (M3): existing evaluation runs into quality evidence.

Reads an ``EvaluationRun`` and its ``CaseResult`` list, exactly as the server
produces them, and returns an ``EvidenceRun``. Read only: the server's models
and its ``PolicyEngine`` are untouched, and this module never imports ``app``.
Runs and case results are read by field name, so it accepts the server's
Pydantic objects or their JSON form (for example an API response).

One check per metric on each case:
    id      ``<dataset_name>::<case_id>::<metric_name>``, stable across dataset
            versions so baselines can compare them
    status  the same classification as ``app/policy/engine.py::_metric_status``,
            now written down explicitly:
              metadata has ``error_type``                  -> error
              a ``*_status`` is ``skipped_missing_input``  -> skipped
              otherwise scored: ``passed`` -> passed, else -> failed
            (A skipped metric has ``passed=True``, meaning "not applicable",
            so the order matters: it is never counted as passed here.)
    metrics ``score`` and ``threshold``; message is the metric's explanation;
            tags are the framework, plus ``critical_failure`` when the case is
            a failed critical case.

One extra check when a case never reached evaluation (approved 2026-11-23):
    A ``CaseResult`` with ``error`` set (the system under test couldn't be
    reached, or the runner isolated a crash) has no metric results. It becomes
    one check ``<dataset_name>::<case_id>::provider`` with status error, so the
    case can't silently drop out of the evidence.

A case that ran but had no applicable evaluator produces no checks, because
nothing was checked. (The M4 policy blocks a run with zero checks.)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from aqg.evidence import (
    CheckEvidence,
    CheckSource,
    CheckStatus,
    EvidenceInput,
    EvidenceRun,
    InputFormat,
)

PROVIDER_CHECK_NAME = "provider"
CRITICAL_TAG = "critical_failure"
SKIPPED_MISSING_INPUT = "skipped_missing_input"


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _text(value: Any, what: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValueError(f"{what} is missing or blank")
    return text


def metric_status(metric: Any) -> CheckStatus:
    """Status of one MetricResult, matching ``PolicyEngine``'s ``_metric_status``."""
    metadata = _field(metric, "metadata") or {}
    if "error_type" in metadata:
        return CheckStatus.ERROR
    status_value = next((v for k, v in metadata.items() if str(k).endswith("_status")), None)
    if status_value == SKIPPED_MISSING_INPUT:
        return CheckStatus.SKIPPED
    passed = _field(metric, "passed")
    if not isinstance(passed, bool):
        raise ValueError(f"metric {_field(metric, 'metric_name')!r} has no boolean 'passed'")
    return CheckStatus.PASSED if passed else CheckStatus.FAILED


def _created_at(run: Any) -> datetime:
    value = _field(run, "started_at")
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime):
        raise ValueError("run.started_at is missing")
    # The server always records UTC (datetime.now(UTC)); a value read back
    # without a timezone is still UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _metric_check(dataset: str, case_id: str, metric: Any, tags: list[str]) -> CheckEvidence:
    name = _text(_field(metric, "metric_name"), f"case {case_id!r}: metric_name")
    framework = _text(_field(metric, "framework"), f"case {case_id!r}: framework of {name!r}")
    return CheckEvidence(
        id=f"{dataset}::{case_id}::{name}",
        name=name,
        suite=dataset,
        source=CheckSource.LLM,
        status=metric_status(metric),
        message=(_field(metric, "explanation") or None),
        metrics={
            "score": float(_field(metric, "score")),
            "threshold": float(_field(metric, "threshold")),
        },
        tags=[framework, *tags],
    )


def _provider_check(dataset: str, case_id: str, error: Any, tags: list[str]) -> CheckEvidence:
    error_type = _field(error, "error_type") or "unknown"
    detail = _field(error, "message")
    return CheckEvidence(
        id=f"{dataset}::{case_id}::{PROVIDER_CHECK_NAME}",
        name=PROVIDER_CHECK_NAME,
        suite=dataset,
        source=CheckSource.LLM,
        status=CheckStatus.ERROR,
        message=f"{error_type}: {detail}" if detail else str(error_type),
        tags=[PROVIDER_CHECK_NAME, *tags],
    )


def evidence_from_llm_run(
    run: Any,
    case_results: Iterable[Any],
    *,
    project: str | None = None,
    commit: str | None = None,
) -> EvidenceRun:
    """Convert one evaluation run and its case results into an ``EvidenceRun``.

    ``project`` defaults to the dataset name and ``version`` is the dataset
    version. Raises ``ValueError`` (or Pydantic's ``ValidationError``) if the
    input is incomplete, for example two metrics with the same name on one case.
    """
    dataset = _text(_field(run, "dataset_name"), "run.dataset_name")
    checks: list[CheckEvidence] = []
    for case in case_results:
        case_id = _text(_field(case, "case_id"), "case_id")
        tags = [CRITICAL_TAG] if _field(case, "critical_failure") else []
        error = _field(case, "error")
        if error:
            checks.append(_provider_check(dataset, case_id, error, tags))
        for metric in _field(case, "metric_results") or []:
            checks.append(_metric_check(dataset, case_id, metric, tags))

    return EvidenceRun(
        project=project or dataset,
        version=_text(_field(run, "dataset_version"), "run.dataset_version"),
        commit=commit,
        created_at=_created_at(run),
        inputs=[
            EvidenceInput(format=InputFormat.LLM, path=_text(_field(run, "id"), "run.id")),
        ],
        checks=checks,
    )
