# Evaluation Strategy

Why this system evaluates the way it does: which frameworks, which
metrics, and the rules that turn many per-case scores into one release
decision. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for how the pieces are
wired together, and `DECISIONS.md` #21–#28 for the full dated rationale
behind each choice below.

## The foundation: deterministic evaluation

Eight evaluators require no LLM judge, no API key, and no network call at
all — they're pure functions over a `CaseResult`:

| Evaluator | What it checks |
|---|---|
| `exact_match` | Response equals (or closely matches, per `match_mode`) an expected answer |
| `required_phrases` | Every required substring/phrase is present |
| `forbidden_phrases` | No forbidden substring/phrase is present |
| `json_schema_compliance` | Structured output validates against the case's declared JSON schema |
| `expected_refusal` | The system refused when it was supposed to (prompt injection, out-of-scope, unsafe requests) |
| `citation_presence` | A RAG answer actually cites retrieved context |
| `latency_ms` | Response time is within a threshold |
| `estimated_cost_usd` | Estimated per-call cost is within a threshold |

**These are the default and the foundation, not an afterthought,
because a release gate has to be trustworthy on its own terms first.**
A gate whose every signal comes from another LLM is a gate you can't
fully explain when it blocks a release — "the judge model said so" is a
weaker answer than "the response contained the forbidden phrase at byte
offset 142." Deterministic checks are:

- **Free** — no API key needed, nothing to disable in CI (see "How does
  CI avoid unnecessary paid calls?" in the README).
- **Instant** — no network round-trip, so the full 40-case golden dataset
  grades in well under a second.
- **Reproducible** — the same input always produces the same score,
  which is what makes them safe as the *default* path and as CI's only
  path.
- **Fully explainable** — every failure traces to a specific rule a human
  can read in `app/evaluation/deterministic.py`.

They can't catch everything, though — "is this answer actually
faithful to the retrieved context" or "does this response have the right
tone" isn't a substring check. That's what the next three frameworks add.

## Why multiple evaluation frameworks

| Framework | Ships | Catches what deterministic checks can't |
|---|---|---|
| **RAGAS** | `ragas_faithfulness`, `ragas_answer_relevancy`, `ragas_context_precision`, `ragas_context_recall` | RAG-specific quality: is the answer actually grounded in what was retrieved, is it relevant to the question, did retrieval itself find the right (and only the right) chunks |
| **DeepEval** | `deepeval_criteria` (G-Eval) | Open-ended qualitative/semantic checks against a natural-language rubric you write per case — tone, policy adherence, "did it ask a clarifying question" — anything a judge model can assess against a description |
| **OpenAI-Evals-concept** | `openai_evals_label_grader`, `openai_evals_structured_correctness` | Closed-set label classification (policy/behavior/quality categories) and fact-checklist-style structured-answer correctness, built directly on OpenAI's Responses API |

Each framework is isolated behind its own `*Client` module
(`app/evaluation/{ragas,deepeval,openai_evals}/client.py`) — the **only**
place that framework's SDK is imported anywhere in the codebase. This
was a real, not theoretical, concern: adding RAGAS surfaced an actual
dependency conflict (`ragas==0.4.3` breaks against
`langchain-community>=0.4.0` — `DECISIONS.md` #21) that isolation
contained to one module's pinned requirements rather than letting it
ripple into every other framework's test suite. The visible cost of this
choice is some structural repetition — all four client modules do a
similar "call the SDK, catch its exceptions, map to a normalized shape"
dance — accepted deliberately (`ARCHITECTURE.md`'s technology-choices
table) because the alternative (one shared SDK-wrapping abstraction)
would mean a dependency conflict in any one framework blocks or breaks
every other one.

All three LLM-judge frameworks are **opt-in and disabled by default**
(`AQG_RAGAS_ENABLED`/`AQG_DEEPEVAL_ENABLED`/`AQG_OPENAI_EVALS_ENABLED`),
reuse the same `AQG_OPENAI_API_KEY`/`AQG_PROVIDER_TIMEOUT_SECONDS` rather
than needing separate credentials to manage, and are independently
selectable per run via an optional `frameworks` request field.

## Why provider-neutral

`app/providers/base.py`'s `Provider` protocol (`name`, `model`,
`generate(request) -> response`) is the only thing `EvaluationRunner`
and every evaluator ever see. `DeterministicProvider` (fixture replay —
what every test and all of CI uses), `OpenAIProvider`, and
`GeminiProvider` all implement it identically. This means:

- **Evaluation logic never depends on a specific vendor's SDK.** Nothing
  in `app/evaluation/` imports `openai` or `google.genai` directly.
- **The same golden dataset, same evaluators, same policy** can grade any
  system under test — swap `"provider": "openai"` for `"provider":
  "gemini"` in a request and nothing else changes.
- **Every provider failure (timeout, rate limit, auth, malformed
  response, unavailable) is normalized** into one `ProviderError` shape
  rather than raising — a provider's own SDK exception never crashes an
  evaluation; see "What happens when an evaluator fails?" below for the
  same principle applied one layer up.
- **CI never needs a real model.** `DeterministicProvider` makes
  provider-neutrality the mechanism that keeps CI both correct (it
  exercises the exact same code path a live provider would) and free.

## Evaluator failure handling

Every evaluator call — regardless of framework — passes through the same
two isolation layers in `EvaluationRunner`:

1. **A wall-clock timeout** (`AQG_EVALUATOR_TIMEOUT_SECONDS`, default
   60s), independent of and in addition to any judge-model HTTP client's
   own timeout — this catches a *non-network* hang (a library bug, a
   pathological input) that an HTTP timeout would never see.
2. **A catch-all exception handler** — any unexpected crash (a bug in
   that specific evaluator or framework) is caught, never propagates.

Either one converts the failure into an explicit `MetricResult` carrying
`metadata["error_type"]` (`"timeout"` or `"unavailable"`) — the same
convention each framework's own client already uses for *its* infra
failures (a judge model rate-limited, timed out, or returned something
unparseable). **This is never a quality score of zero** — a required
metric's `on_infrastructure_failure` policy setting (block/warn/ignore)
governs it, completely separately from `on_missing` (the metric never ran
at all) and from an actual low score (the judge ran fine and said the
response was bad).

One evaluator failing — by any of these mechanisms — never stops another
evaluator (any framework) from grading the same case, and one case
failing never loses another case's already-computed result for the same
run. `CaseResult.partial` is `True` whenever *any* metric for that case
carries `error_type` — whether from a framework's own infra failure or
this isolation mechanism — making "this case's evaluation is incomplete"
an explicit, queryable fact rather than something a reader has to infer
from absence.

## How critical cases are handled

A golden dataset case can be marked `critical: true` — "if the system
gets this wrong, that's not just a lower pass rate, it's a specific,
named failure that matters on its own" (a prompt-injection case, a
safety-refusal case, a legally-sensitive structured-output case).
`CaseResult.critical_failure` is `True` whenever a critical case's
`passed` is `False`. The policy's `critical_case_action` (`block` or
`warn` — deliberately **never** `ignore`, since a case existing as
"critical" at all means someone marked it non-negotiable) governs what
that does to the release decision. `GateDecision.critical_failures` lists
every failing critical case's id directly, so "what specifically failed"
never requires cross-referencing the full case list.

## How baselines and regressions work

Approving a run's results as a dataset's `Baseline`
(`POST /gate/baselines`) records that run's pass rate and
per-metric aggregate scores as the comparison point for every future run
against that same dataset. A later gate decision against the same
dataset automatically compares against the *latest* approved baseline
(not every historical one — `PROJECT_STATE.md`'s Outstanding Work notes
this as a known scope limit) and flags a regression when the drop in
pass rate or any metric's aggregate exceeds
`max_regression_tolerance` (0.0 by default — any regression at all is
flagged). `regression_action` (block/warn) governs what that does to the
decision; `GateDecision.regression_summary` carries the specific deltas
and any newly-failing or newly-recovered cases.

## How release policy ties it together

`app/policy/engine.py`'s `PolicyEngine.decide()` is the **only** function
in the entire codebase that computes PASS/WARN/BLOCK — see
`ARCHITECTURE.md`'s decision-flow diagram for the exact order of checks.
Three conditions are hard-coded, never policy-configurable, because
they're definitional rather than a judgment call:

- **Vacuous-pass guard**: if a run produced zero scored `MetricResult`s
  anywhere, it's BLOCK unconditionally — a policy with no required
  metrics configured must never silently "pass" a run that evaluated
  nothing.
- **Pass rate below `min_pass_rate`**: always BLOCK.
- **A required metric's aggregate score below its own `min_score`**:
  always BLOCK.

Everything else — a required metric missing or infra-failed, a critical
case failing, a regression, a latency/cost budget — is configurable
per-policy as `block`/`warn`(/`ignore` where offered), letting different
teams or rollout phases set different bars without touching any
evaluation or orchestration code.

## How Phoenix helps

Arize Phoenix (via OpenTelemetry) is purely observational — it answers
*"what happened during this run"*, never *"was the run good enough to
release"* (that's the Policy Engine's job, and the two are architecturally
incapable of overlapping — see `ARCHITECTURE.md`'s layer table). When
enabled, every run gets a full span tree: `evaluation_run` → `case` →
`provider_call` (→ `retrieval`, for RAG cases, nested so retrieval and
generation are visibly separate) and one span per evaluator, each
carrying latency, token counts, cost, and pass/fail. A run's `trace_id`
is persisted on both the `EvaluationRun` and the `GateDecision` it
produced, so a human reading an audit record can jump straight to the
full trace. It's entirely optional (`AQG_TRACING_ENABLED`, off by
default) and degrades to a no-op tracer with zero behavior change if
Phoenix is unreachable or misconfigured — see `docs/debugging-failed-runs.md`
for the practical "my run failed, where do I look" walkthrough.
