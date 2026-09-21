# Debugging failed runs with Phoenix

This is a task-oriented companion to `PROJECT_STATE.md`'s Sprint 9 section
and `DECISIONS.md` #30 — start there for the architecture; start here when
you actually have a run that failed or looked wrong and want to know why.

## 1. Turn tracing on

Tracing is off by default. Point it at a local Phoenix instance:

```bash
# Phoenix runs as its own process - it is not a dependency of this app.
# Either of these works:
pip install arize-phoenix && phoenix serve
# or
docker run -p 6006:6006 arizephoenix/phoenix:latest

# then start the Gate with tracing enabled:
AQG_TRACING_ENABLED=true \
  AQG_PHOENIX_COLLECTOR_ENDPOINT=http://localhost:6006/v1/traces \
  uv run uvicorn app.main:app --reload
```

Open `http://localhost:6006` in a browser — this is Phoenix's own UI,
separate from the Gate's API docs at `/docs`.

If Phoenix isn't running (or isn't reachable), the app still starts and
serves requests exactly as before — `configure_tracing()` catches any
setup failure and falls back to a no-op tracer. You'll just have no traces
to look at. Nothing else about the Gate's behavior changes.

## 2. Run the evaluation and get its trace id

```bash
curl -X POST http://127.0.0.1:8000/api/v1/evaluations/runs \
  -H "Content-Type: application/json" \
  -d '{"dataset_name": "customer_support_bot", "dataset_version": "1.1.0"}'
```

The response's `run.trace_id` is a 32-hex-digit string — paste it into
Phoenix's search bar to jump straight to this run's trace. It's `null` if
tracing wasn't enabled for this run.

If you already have a `GateDecision` instead of the raw run (from `POST
/gate/decisions`), its `trace_id` field is the same value, copied from the
run it decided about — you don't need to look the run up separately.

```bash
curl http://127.0.0.1:8000/api/v1/gate/decisions/<decision_id>
# -> {"trace_id": "22f98bd664e1bb662a54ba93ba266d4b", "status": "block", ...}
```

## 3. Reading the trace

Every run produces one trace with this span shape:

```
evaluation_run                              (dataset, provider, model, case count)
└── case                                    (one per case: id, category, critical flag)
    ├── provider_call                       (provider, model, latency, tokens, cost)
    │   └── retrieval                       (RAG cases only — query, chunks retrieved)
    ├── <evaluator name>                    (one per applicable evaluator)
    ├── <evaluator name>
    └── ...
```

Start at the case that failed (filter by `case.id` in Phoenix, or open the
trace and expand). From there:

- **The system under test produced a bad/wrong answer** → open the
  `provider_call` span. `llm.model_name`, `llm.token_count.prompt`/
  `llm.token_count.completion`, `llm.latency_ms`, and `input.value`/
  `output.value` are all on this span. An `error.type`/`error.message`
  pair here means the provider itself failed (timeout, rate limit,
  authentication, ...) — the case never reached evaluation at all in that
  case (`CaseResult.metric_results` is empty, `passed=False`).
- **A RAG case's answer looks ungrounded, or cites the wrong thing** →
  open the `retrieval` span nested under `provider_call`. Its
  `retrieval.chunk_count` and `retrieval.documents.N.document.content`/
  `.document.score` attributes are exactly what was retrieved and how
  relevant each chunk scored — compare that against what the answer
  actually says. Retrieval and generation are separate spans specifically
  so you can tell "we retrieved the wrong thing" apart from "we retrieved
  the right thing but generated a bad answer from it."
- **An evaluator's verdict looks wrong, or you're not sure why a metric
  failed** → open that evaluator's own span (named after the evaluator,
  e.g. `ragas_faithfulness`, `deepeval_criteria`,
  `openai_evals_label_grader`). `evaluator.score`, `evaluator.passed`, and
  `evaluator.metric_name` are there. This span exists identically for
  every framework — deterministic, RAGAS, DeepEval, and the OpenAI-Evals-
  concept evaluators are all instrumented the same way, so the same
  debugging steps apply regardless of which framework produced the metric
  you're looking at.
- **An evaluator's framework itself seems to have broken** (not a bad
  score — no score at all) → this shows up in the evaluator's span same
  as above, but check the `MetricResult` in the case's own API response
  first: `metadata["error_type"]` present means an evaluator
  infrastructure failure (RAGAS/DeepEval/OpenAI-Evals judge timeout, rate
  limit, auth, malformed response, ...), not a quality score of 0 — see
  `DECISIONS.md` #22/#24/#26 for why those are kept distinct. The gate
  decision's own `framework_errors` field (`GET /gate/decisions/{id}`)
  gives you the run-wide count of these per metric without having to open
  every case's spans individually.

## 4. What tracing does NOT tell you

Phoenix shows you *what happened* during a run. It has no opinion on
*whether the run should have passed* — that's `PolicyEngine`'s job
(`app/policy/`), and it's a completely separate question from tracing.
`GateDecision.reasons`/`aggregate_metrics`/`critical_failures`/
`regression_summary` (via `GET /gate/decisions/{id}`) is where you look
for the actual PASS/WARN/BLOCK reasoning; a trace can help you understand
*why* a metric scored the way it did, but never explains the release
decision itself, because Phoenix never computes one (see DECISIONS.md #30
and the "Phoenix observes; it never decides" note in `PROJECT_STATE.md`).

## 5. Debugging tracing itself

If `run.trace_id` is unexpectedly `null` even with `AQG_TRACING_ENABLED=true`:
check the app's startup logs for a warning from `app.observability.tracing`
("Phoenix tracing could not be configured..."). That means setup itself
failed (bad endpoint, Phoenix unreachable at the time `register()` ran,
etc.) and the app silently fell back to the no-op tracer — the run still
completed correctly, it just wasn't traced. Fix the endpoint/connectivity
and restart; there's no way to "turn tracing on" retroactively for a run
that already happened.
