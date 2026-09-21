from app.reports.report import Report, build_report
from app.services.policy_service import PolicyService


class ReportService:
    """Thin composition over `PolicyService`: fetches a decision plus its
    run and case results, and assembles them into one downloadable
    `Report` (requirement: JSON/HTML reports). Not a new source of truth —
    see `app/reports/report.py`'s module docstring."""

    def __init__(self, policy_service: PolicyService) -> None:
        self._policy_service = policy_service

    def get_report(self, decision_id: str) -> Report:
        decision = self._policy_service.get_decision(decision_id)
        run, case_results = self._policy_service.get_run_and_results(decision.run_id)
        return build_report(decision, run, case_results)
