"""Renders a `Report` as one self-contained HTML file — no template engine
dependency (Jinja2 etc.): the report is a fixed, simple shape, and plain
f-strings keep this module dependency-free, matching the "isolated
observability module" precedent Sprint 9 set for similarly self-contained
concerns. All dynamic values are HTML-escaped via `html.escape`.
"""

from html import escape

from app.reports.report import Report

_STATUS_COLORS = {
    "pass": "#1a7f37",
    "warn": "#9a6700",
    "block": "#cf222e",
}

_CSS = """
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
       margin: 2rem; color: #1f2328; }
h1 { font-size: 1.4rem; }
h2 { font-size: 1.05rem; margin-top: 2rem; border-bottom: 1px solid #d0d7de;
     padding-bottom: 0.25rem; }
table { border-collapse: collapse; width: 100%; margin-top: 0.5rem; font-size: 0.9rem; }
th, td { border: 1px solid #d0d7de; padding: 0.4rem 0.6rem; text-align: left;
         vertical-align: top; }
th { background: #f6f8fa; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.85em; }
.badge { display: inline-block; padding: 0.15rem 0.6rem; border-radius: 0.3rem;
         color: white; font-weight: 600; text-transform: uppercase; font-size: 0.8rem; }
.muted { color: #59636e; }
.case-fail { background: #fff8f8; }
.case-critical { background: #ffebe9; }
"""


def render_html(report: Report) -> str:
    status = report.status.value if hasattr(report.status, "value") else str(report.status)
    color = _STATUS_COLORS.get(status, "#59636e")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Evaluation Report — {escape(report.run_id)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>AI Quality Gate — Evaluation Report
  <span class="badge" style="background:{color}">{escape(status)}</span>
</h1>
<p class="muted">Generated {escape(report.generated_at.isoformat())}</p>

{_render_reasons(report)}
{_render_run_metadata(report)}
{_render_aggregate_metrics(report)}
{_render_critical_failures(report)}
{_render_regression_summary(report)}
{_render_framework_errors(report)}
{_render_case_results(report)}
</body>
</html>
"""


def _render_reasons(report: Report) -> str:
    if not report.reasons:
        return ""
    items = "".join(f"<li>{escape(r)}</li>" for r in report.reasons)
    return f"<h2>Reasons</h2><ul>{items}</ul>"


def _render_run_metadata(report: Report) -> str:
    completed_cell = escape(report.completed_at.isoformat()) if report.completed_at else "-"
    cases_cell = f"{report.passed_cases} / {report.total_cases} passed ({report.pass_rate:.1%})"
    trace_row = (
        f"<tr><th>Trace ID</th><td><code>{escape(report.trace_id)}</code></td></tr>"
        if report.trace_id
        else '<tr><th>Trace ID</th><td class="muted">not traced</td></tr>'
    )
    return f"""<h2>Run metadata</h2>
<table>
<tr><th>Run ID</th><td><code>{escape(report.run_id)}</code></td></tr>
<tr><th>Decision ID</th><td><code>{escape(report.decision_id)}</code></td></tr>
<tr><th>Dataset</th><td>{escape(report.dataset_name)} @ {escape(report.dataset_version)}</td></tr>
<tr><th>Provider / Model</th><td>{escape(report.provider)} / {escape(report.model)}</td></tr>
<tr><th>Policy</th><td>{escape(report.policy_id)} (v{escape(report.policy_version)})</td></tr>
<tr><th>Started</th><td>{escape(report.started_at.isoformat())}</td></tr>
<tr><th>Completed</th><td>{completed_cell}</td></tr>
{trace_row}
<tr><th>Cases</th><td>{cases_cell}</td></tr>
<tr><th>Mean latency</th><td>{report.mean_latency_ms:.0f} ms</td></tr>
<tr><th>Tokens (in/out)</th><td>{report.total_input_tokens} / {report.total_output_tokens}</td></tr>
<tr><th>Total estimated cost</th><td>${report.total_estimated_cost:.4f}</td></tr>
</table>"""


def _render_aggregate_metrics(report: Report) -> str:
    if not report.aggregate_metrics:
        return '<h2>Aggregate metrics</h2><p class="muted">No scored metrics in this run.</p>'
    rows = "".join(
        f"<tr><td><code>{escape(name)}</code></td><td>{score:.3f}</td></tr>"
        for name, score in sorted(report.aggregate_metrics.items())
    )
    return (
        "<h2>Aggregate metrics</h2><table>"
        f"<tr><th>Metric</th><th>Mean score</th></tr>{rows}</table>"
    )


def _render_critical_failures(report: Report) -> str:
    if not report.critical_failures:
        return ""
    items = "".join(f"<li><code>{escape(c)}</code></li>" for c in report.critical_failures)
    return f"<h2>Critical failures</h2><ul>{items}</ul>"


def _render_regression_summary(report: Report) -> str:
    summary = report.regression_summary
    if summary is None:
        return ""
    deltas = "".join(
        f"<tr><td><code>{escape(name)}</code></td><td>{delta:+.3f}</td></tr>"
        for name, delta in sorted(summary.metric_deltas.items())
    )
    new_failures = ", ".join(summary.new_failures) or "none"
    recovered = ", ".join(summary.recovered_failures) or "none"
    return f"""<h2>Regression vs. baseline v{summary.baseline_version}</h2>
<table>
<tr><th>Pass rate delta</th><td>{summary.pass_rate_delta:+.2%}</td></tr>
<tr><th>New failures</th><td>{escape(new_failures)}</td></tr>
<tr><th>Recovered failures</th><td>{escape(recovered)}</td></tr>
</table>
<table><tr><th>Metric</th><th>Delta</th></tr>{deltas}</table>"""


def _render_framework_errors(report: Report) -> str:
    if not report.framework_errors:
        return ""
    rows = "".join(
        f"<tr><td><code>{escape(name)}</code></td><td>{count}</td></tr>"
        for name, count in sorted(report.framework_errors.items())
    )
    return f"""<h2>Evaluator infrastructure errors</h2>
<p class="muted">Counts below are execution failures, never quality scores of 0.</p>
<table><tr><th>Metric</th><th>Failure count</th></tr>{rows}</table>"""


def _render_case_results(report: Report) -> str:
    rows = []
    for case in report.case_results:
        row_class = (
            "case-critical" if case.critical_failure else ("case-fail" if not case.passed else "")
        )
        metrics = (
            "; ".join(
                f"{escape(m.metric_name)}={m.score:.3f}{'✓' if m.passed else '✗'}"
                for m in case.metric_results
            )
            or '<span class="muted">none</span>'
        )
        error_cell = escape(case.error["message"]) if case.error else "-"
        result_label = "PASS" if case.passed else "FAIL"
        critical_suffix = " (critical)" if case.critical_failure else ""
        rows.append(
            f'<tr class="{row_class}">'
            f"<td><code>{escape(case.case_id)}</code></td>"
            f"<td>{result_label}{critical_suffix}</td>"
            f"<td>{case.latency_ms:.0f} ms</td>"
            f"<td>{case.input_tokens}/{case.output_tokens}</td>"
            f"<td>${case.estimated_cost:.4f}</td>"
            f"<td>{metrics}</td>"
            f"<td>{error_cell}</td>"
            f"</tr>"
        )
    return f"""<h2>Per-case results ({report.total_cases})</h2>
<table>
<tr><th>Case</th><th>Result</th><th>Latency</th><th>Tokens</th><th>Cost</th><th>Metrics</th><th>Error</th></tr>
{"".join(rows)}
</table>"""
