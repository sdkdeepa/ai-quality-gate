"""Isolated observability module (Sprint 9 requirement: "isolated
observability module"). This is the only place in the codebase that
imports `phoenix`/`openinference`/`opentelemetry` for *setup* purposes —
`app/evaluation/runner.py` and `app/rag/retriever.py` (the two
instrumentation call sites) only ever receive a plain `opentelemetry.trace.Tracer`
from `configure_tracing()` below, the same standard OTel API object either
way, so they don't need to know or care whether tracing is actually
enabled, Phoenix is reachable, or any of this package's dependencies are
even installed correctly.

Phoenix must not own release policy (explicit sprint requirement): nothing
here reads a `MetricResult`, computes a score, or produces a
`GateDecision` — `app/policy/` has no idea this module exists, and this
module never imports anything from `app/policy/`. This module only ever
emits spans *describing* what already happened elsewhere; it never
decides anything.
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.trace import Span, Tracer

logger = logging.getLogger(__name__)

TRACER_NAME = "ai_quality_gate"


def configure_tracing(
    *,
    enabled: bool,
    collector_endpoint: str,
    project_name: str,
) -> Tracer:
    """Returns a `Tracer`.

    When `enabled` is True and setup against Phoenix succeeds, the tracer
    is bound to a real `TracerProvider` exporting to `collector_endpoint`.
    In every other case — `enabled=False`, or setup raised for any reason
    (Phoenix unreachable at export time is NOT a setup-time error and
    would not land here anyway, but a bad endpoint URL, a missing/broken
    dependency, or anything else unexpected might) — this returns
    OpenTelemetry's own built-in no-op tracer via the plain `trace` API.

    This function never raises. Every span-creation call site elsewhere in
    the app (`tracer.start_as_current_span(...)`) is byte-identical
    whether tracing is enabled or not — a no-op tracer's spans are
    harmless, near-zero-cost, and satisfy the same context-manager
    protocol as a real one. This is what makes "app works when Phoenix is
    unavailable" and "tracing configurable on/off" hold with no special
    casing anywhere outside this one function.

    Deliberately does NOT call `set_global_tracer_provider` (the
    `phoenix.otel.register()` default): OpenTelemetry only allows the
    *global* tracer provider to be set once per process and silently
    ignores later attempts, which would make repeated `create_app()` calls
    (every test in this suite does this) behave inconsistently depending
    on execution order. Instead, the returned `Tracer` is bound directly
    to its own `TracerProvider` instance and threaded through explicit
    constructor injection (`EvaluationRunner(tracer=...)`,
    `Retriever(tracer=...)`) — ordinary dependency injection, the same
    pattern `Provider`/`Evaluator` already use, rather than relying on any
    process-global OpenTelemetry state.
    """
    if not enabled:
        return trace.get_tracer(TRACER_NAME)

    try:
        from phoenix.otel import register

        provider = register(
            endpoint=collector_endpoint,
            project_name=project_name,
            batch=True,
            set_global_tracer_provider=False,
            verbose=False,
        )
        return provider.get_tracer(TRACER_NAME)
    except Exception:
        logger.warning(
            "Phoenix tracing could not be configured (endpoint=%s); continuing without tracing.",
            collector_endpoint,
            exc_info=True,
        )
        return trace.get_tracer(TRACER_NAME)


def trace_id_hex(span: Span) -> str | None:
    """The span's trace id as the standard 32-hex-digit string (the form
    Phoenix/Jaeger/most OTel backends display and link to) — or `None` for
    a no-op/invalid span context, i.e. tracing is disabled or failed to
    configure. Used to populate `EvaluationRun.trace_id`/
    `GateDecision.trace_id` (requirement: "trace IDs persisted with runs
    ... correlated to audit records")."""
    context = span.get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")
