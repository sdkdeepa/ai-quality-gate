"""Sprint 9 requirement: "tests for observability boundary, graceful
failure, trace propagation". This file covers `configure_tracing` itself
(the observability boundary and its graceful-failure behavior);
`test_instrumentation.py` covers trace propagation through the actual
instrumented components (`EvaluationRunner`, `Retriever`).

Deliberately never calls the real `phoenix.otel.register()` against an
unreachable collector in these tests: span *creation* never touches the
network (only background export does, on its own thread, with its own
retry/backoff), so a test that did this would still pass, but would also
spawn a lingering background exporter thread retrying against a closed
port for several seconds per test - slow and noisy for no additional
coverage. The "enabled and Phoenix is reachable" path is covered by
`test_instrumentation.py` using a plain OpenTelemetry TracerProvider
(no Phoenix involved) - `configure_tracing` just decides which
TracerProvider backs the returned Tracer, and that decision is exactly
what's under test here.
"""

from app.observability.tracing import configure_tracing, trace_id_hex


class TestConfigureTracingDisabled:
    def test_disabled_returns_a_tracer_whose_spans_have_no_trace_id(self):
        tracer = configure_tracing(
            enabled=False,
            collector_endpoint="http://localhost:6006/v1/traces",
            project_name="test",
        )

        with tracer.start_as_current_span("x") as span:
            assert trace_id_hex(span) is None

    def test_disabled_never_imports_phoenix(self, monkeypatch):
        """Confirms the disabled path really is a no-op short-circuit, not
        just one that happens to succeed - registration code must not even
        run when tracing is off."""
        import sys

        def _boom(**kwargs):
            raise AssertionError("phoenix.otel.register should not be called when disabled")

        fake_module = type(sys)("phoenix.otel")
        fake_module.register = _boom
        monkeypatch.setitem(sys.modules, "phoenix.otel", fake_module)

        tracer = configure_tracing(
            enabled=False,
            collector_endpoint="http://localhost:6006/v1/traces",
            project_name="test",
        )
        with tracer.start_as_current_span("x"):
            pass  # no AssertionError raised means register() was never called


class TestConfigureTracingGracefulFailure:
    """ "App works when Phoenix is unavailable" - registration itself
    failing (bad config, import error, anything else) must never raise
    out of configure_tracing, and must fall back to a working (no-op)
    tracer so the rest of the app is completely unaffected."""

    def test_registration_failure_falls_back_to_a_working_tracer(self, monkeypatch):
        import sys

        fake_module = type(sys)("phoenix.otel")

        def _boom(**kwargs):
            raise RuntimeError("simulated Phoenix registration failure")

        fake_module.register = _boom
        monkeypatch.setitem(sys.modules, "phoenix.otel", fake_module)

        tracer = configure_tracing(
            enabled=True,
            collector_endpoint="http://localhost:6006/v1/traces",
            project_name="test",
        )

        # Must not raise, and must still behave as a valid tracer.
        with tracer.start_as_current_span("x") as span:
            assert trace_id_hex(span) is None

    def test_registration_failure_logs_a_warning(self, monkeypatch, caplog):
        import logging
        import sys

        fake_module = type(sys)("phoenix.otel")
        fake_module.register = lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        monkeypatch.setitem(sys.modules, "phoenix.otel", fake_module)

        with caplog.at_level(logging.WARNING, logger="app.observability.tracing"):
            configure_tracing(
                enabled=True,
                collector_endpoint="http://localhost:6006/v1/traces",
                project_name="test",
            )

        assert any("could not be configured" in record.message for record in caplog.records)


class TestTraceIdHex:
    def test_formats_a_valid_trace_id_as_32_hex_digits(self):
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(InMemorySpanExporter()))
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("x") as span:
            trace_id = trace_id_hex(span)

        assert trace_id is not None
        assert len(trace_id) == 32
        assert all(c in "0123456789abcdef" for c in trace_id)

    def test_returns_none_for_a_no_op_span(self):
        from opentelemetry import trace

        tracer = trace.get_tracer("test-noop")
        with tracer.start_as_current_span("x") as span:
            assert trace_id_hex(span) is None
