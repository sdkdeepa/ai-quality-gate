"""Small presentation-only helpers shared across API routers.

Not domain logic — `CaseResult`/`MetricResult` stay framework-agnostic
(Sprint 1/2's layering principle). This just re-groups the metric results a
case already carries by `framework`, so a caller can see deterministic vs.
RAGAS results for the same case side by side (Sprint 5 requirement #8)
without a frontend or a change to the domain models themselves.
"""

from app.domain.case_result import CaseResult
from app.domain.metric_result import MetricResult


def metrics_by_framework(case_result: CaseResult) -> dict[str, list[MetricResult]]:
    grouped: dict[str, list[MetricResult]] = {}
    for metric in case_result.metric_results:
        grouped.setdefault(metric.framework, []).append(metric)
    return grouped
