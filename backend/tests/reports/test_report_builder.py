from app.domain.case_result import CaseResult
from app.domain.enums import GateStatus
from app.domain.evaluation_run import EvaluationRun
from app.domain.gate_decision import GateDecision, RegressionSummary
from app.domain.metric_result import MetricResult
from app.reports.html import render_html
from app.reports.report import build_report


def _run(**overrides) -> EvaluationRun:
    defaults = {
        "dataset_name": "support_bot",
        "dataset_version": "1.0.0",
        "provider": "deterministic",
        "model": "fixture-v1",
        "trace_id": "22f98bd664e1bb662a54ba93ba266d4b",
    }
    defaults.update(overrides)
    return EvaluationRun(**defaults)


def _decision(**overrides) -> GateDecision:
    defaults = {
        "run_id": "run-1",
        "dataset_version": "1.0.0",
        "provider": "deterministic",
        "model": "fixture-v1",
        "policy_id": "policy-1",
        "policy_version": "1.0.0",
        "status": GateStatus.BLOCK,
        "reasons": ["pass rate too low"],
        "trace_id": "22f98bd664e1bb662a54ba93ba266d4b",
    }
    defaults.update(overrides)
    return GateDecision(**defaults)


def _case(**overrides) -> CaseResult:
    defaults = {
        "case_id": "c1",
        "response": "ok",
        "latency_ms": 100.0,
        "input_tokens": 5,
        "output_tokens": 5,
        "estimated_cost": 0.001,
        "passed": True,
        "metric_results": [],
    }
    defaults.update(overrides)
    return CaseResult(**defaults)


class TestBuildReport:
    def test_report_carries_decision_and_run_identity(self):
        run = _run()
        decision = _decision(run_id=run.id)
        report = build_report(decision, run, [])

        assert report.decision_id == decision.id
        assert report.run_id == run.id
        assert report.status == GateStatus.BLOCK
        assert report.dataset_name == "support_bot"
        assert report.dataset_version == "1.0.0"
        assert report.provider == "deterministic"
        assert report.model == "fixture-v1"
        assert report.trace_id == "22f98bd664e1bb662a54ba93ba266d4b"

    def test_aggregates_are_computed_from_case_results(self):
        cases = [
            _case(
                case_id="c1",
                passed=True,
                latency_ms=100.0,
                input_tokens=10,
                output_tokens=5,
                estimated_cost=0.01,
            ),
            _case(
                case_id="c2",
                passed=False,
                latency_ms=300.0,
                input_tokens=20,
                output_tokens=10,
                estimated_cost=0.02,
            ),
        ]
        report = build_report(_decision(), _run(), cases)

        assert report.total_cases == 2
        assert report.passed_cases == 1
        assert report.pass_rate == 0.5
        assert report.mean_latency_ms == 200.0
        assert report.total_input_tokens == 30
        assert report.total_output_tokens == 15
        assert report.total_estimated_cost == 0.03

    def test_empty_case_results_do_not_divide_by_zero(self):
        report = build_report(_decision(), _run(), [])

        assert report.total_cases == 0
        assert report.pass_rate == 1.0
        assert report.mean_latency_ms == 0.0

    def test_per_case_results_are_included_verbatim(self):
        case = _case(
            metric_results=[
                MetricResult(
                    metric_name="exact_match",
                    score=1.0,
                    threshold=1.0,
                    passed=True,
                    framework="deterministic",
                )
            ]
        )
        report = build_report(_decision(), _run(), [case])

        assert len(report.case_results) == 1
        assert report.case_results[0].metric_results[0].metric_name == "exact_match"

    def test_carries_regression_summary_and_framework_errors(self):
        decision = _decision(
            regression_summary=RegressionSummary(
                baseline_version=2, pass_rate_delta=-0.1, new_failures=["ragas_faithfulness"]
            ),
            baseline_version=2,
            framework_errors={"ragas_context_recall": 1},
        )
        report = build_report(decision, _run(), [])

        assert report.regression_summary.new_failures == ["ragas_faithfulness"]
        assert report.baseline_version == 2
        assert report.framework_errors == {"ragas_context_recall": 1}


class TestRenderHtml:
    def test_renders_status_badge(self):
        report = build_report(_decision(status=GateStatus.BLOCK), _run(), [])
        html = render_html(report)

        assert "block" in html.lower()
        assert report.run_id in html

    def test_renders_reasons_when_present(self):
        report = build_report(_decision(reasons=["critical case c1 failed"]), _run(), [])
        html = render_html(report)

        assert "critical case c1 failed" in html

    def test_omits_reasons_section_when_empty(self):
        report = build_report(_decision(reasons=[]), _run(), [])
        html = render_html(report)

        assert "<h2>Reasons</h2>" not in html

    def test_renders_case_results_table(self):
        case = _case(case_id="c-42", passed=False, critical_failure=True)
        report = build_report(_decision(), _run(), [case])
        html = render_html(report)

        assert "c-42" in html
        assert "critical" in html.lower()

    def test_escapes_untrusted_content(self):
        case = _case(
            case_id="c1",
            error={"error_type": "unavailable", "message": "<script>alert(1)</script>"},
        )
        report = build_report(_decision(), _run(), [case])
        html = render_html(report)

        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_renders_trace_id_when_present(self):
        report = build_report(_decision(trace_id="abc123"), _run(), [])
        html = render_html(report)

        assert "abc123" in html

    def test_renders_no_trace_placeholder_when_absent(self):
        report = build_report(_decision(trace_id=None), _run(trace_id=None), [])
        html = render_html(report)

        assert "not traced" in html

    def test_renders_regression_summary_when_present(self):
        decision = _decision(
            regression_summary=RegressionSummary(
                baseline_version=1, pass_rate_delta=-0.2, new_failures=["exact_match"]
            ),
            baseline_version=1,
        )
        report = build_report(decision, _run(), [])
        html = render_html(report)

        assert "baseline v1" in html.lower()
        assert "exact_match" in html

    def test_produces_valid_looking_html_document(self):
        report = build_report(_decision(), _run(), [])
        html = render_html(report)

        assert html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in html
