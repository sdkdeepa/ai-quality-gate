from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.deps import get_report_service
from app.reports.html import render_html
from app.services.report_service import ReportService

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{decision_id}/json")
def get_report_json(
    decision_id: str,
    report_service: Annotated[ReportService, Depends(get_report_service)],
) -> JSONResponse:
    """Downloadable JSON report for one GateDecision (requirement: PASS/
    WARN/BLOCK, run metadata, dataset version, provider/model, policy
    version, aggregate metrics, per-case results, critical failures,
    regressions, latency, token usage, estimated cost, framework errors,
    trace ID — all in `app/reports/report.py`'s `Report` model)."""
    report = report_service.get_report(decision_id)
    return JSONResponse(
        content=report.model_dump(mode="json"),
        headers={"Content-Disposition": f'attachment; filename="report-{report.run_id}.json"'},
    )


@router.get("/{decision_id}/html")
def get_report_html(
    decision_id: str,
    report_service: Annotated[ReportService, Depends(get_report_service)],
) -> HTMLResponse:
    """Downloadable, self-contained HTML report for one GateDecision — same
    content as the JSON report, rendered for a human to read directly
    (`app/reports/html.py`, no template-engine dependency)."""
    report = report_service.get_report(decision_id)
    html = render_html(report)
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="report-{report.run_id}.html"'},
    )
